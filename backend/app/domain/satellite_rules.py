"""Pure satellite-domain validation; no database, service or device writes.

``nodes`` and ``links`` use the observed CSV column names. Numeric CSV strings
are converted explicitly, then validated against the actual OWL class schema.
Topology validation is not a routing feasibility verdict: aggregate traffic,
allowed exits and SLA checks remain the routing handler's responsibility.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.domain import reasoner


RULE_VERSION = "satellite-planning-v1"
_RULES = (
    ("NET-TYPE", "对象和关系必须符合领域本体", "domain"),
    ("NET-ID", "节点和链路标识不能为空或重复", "domain"),
    ("NET-CAPACITY", "声明的容量必须大于0，传播时延不得为负", "domain"),
    ("NET-ENDPOINT", "链路两端必须存在、不同且方向明确", "domain"),
    ("NET-TIME", "有效时间窗必须有时区且起点早于终点", "domain"),
    ("NET-SNAPSHOT", "快照仅包含分析时刻有效且截止时已知的对象", "snapshot"),
    ("PLAN-PATH", "候选路径连续并保持业务源与允许出口", "routing_handler"),
    ("PLAN-LOAD", "所有迁移业务同时加入后不得超容量或损伤原业务", "routing_handler"),
    ("PLAN-SLA", "校验模型时延上限；可用度等其他SLA仍需实测验证", "routing_handler"),
)
_NUMERIC_FIELDS = {
    "forwarding_capacity_mbps", "nominal_bus_voltage_v",
    "nominal_capacity_mbps", "propagation_latency_ms",
}
_COMMON_FIELDS = {"case_id", "provenance", "available_at", "description"}
_NODE_FIELDS = _COMMON_FIELDS | {
    "node_type", "constellation", "forwarding_capacity_mbps",
    "nominal_bus_voltage_v", "valid_from", "valid_to_exclusive",
}
_LINK_FIELDS = _COMMON_FIELDS | {
    "source_node_id", "target_node_id", "direction", "link_type",
    "nominal_capacity_mbps", "propagation_latency_ms", "visible_from",
    "visible_to_exclusive", "visibility_source",
}


def describe_satellite_rules() -> list[dict[str, str]]:
    """Return rule descriptions with an explicit responsible execution layer."""
    return [
        {"rule_id": key, "description": description, "executor": executor,
         "rule_version": RULE_VERSION}
        for key, description, executor in _RULES
    ]


def _present(value: Any) -> bool:
    return value is not None and value != ""


def _rows(value: Any, label: str, errors: list[str]) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        errors.append(f"[NET-TYPE] {label} 必须是对象列表")
        return []
    result = []
    for index, row in enumerate(value):
        if not isinstance(row, dict):
            errors.append(f"[NET-TYPE] {label}[{index}] 必须是对象")
        else:
            result.append(row)
    return result


def _properties(row: dict[str, Any], identifier: Any, allowed: set[str]) -> dict[str, Any]:
    properties = {key: value for key, value in row.items() if key in allowed and _present(value)}
    properties["external_id"] = identifier
    for key in _NUMERIC_FIELDS & properties.keys():
        value = properties[key]
        if isinstance(value, str):
            try:
                properties[key] = float(value)
            except ValueError:
                # Keep invalid values so the OWL-driven validator rejects them.
                pass
    return properties


def _parse_time(value: Any, label: str, errors: list[str], rule: str = "NET-TIME") -> datetime | None:
    if not isinstance(value, str):
        errors.append(f"[{rule}] {label} 必须是带时区的ISO时间")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError("timezone required")
        return parsed
    except (ValueError, TypeError):
        errors.append(f"[{rule}] {label} 必须是带时区的ISO时间")
        return None


def _check_window(row: dict[str, Any], label: str, start: str, end: str, errors: list[str]) -> None:
    if not _present(row.get(start)) and not _present(row.get(end)):
        return
    left = _parse_time(row.get(start), f"{label}.{start}", errors)
    right = _parse_time(row.get(end), f"{label}.{end}", errors)
    if left is not None and right is not None and left >= right:
        errors.append(f"[NET-TIME] {label} 时间窗必须满足起点早于终点")


def _validate_entity(class_name: str, identifier: Any, row: dict[str, Any], fields: set[str],
                     entities: list[dict[str, Any]], errors: list[str]) -> None:
    properties = _properties(row, identifier, fields)
    title = row.get("title", identifier)
    status = row.get("status", "active")
    result = reasoner.validate_instance(class_name, title, status, properties)
    errors.extend(f"[NET-TYPE] {identifier}: {message}" for message in result.errors)
    entities.append({"id": identifier, "class_name": class_name, "title": title,
                     "status": status, "properties": properties})
    for key in ("forwarding_capacity_mbps", "nominal_capacity_mbps", "propagation_latency_ms"):
        value = properties.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        if key == "propagation_latency_ms" and value < 0:
            errors.append(f"[NET-CAPACITY] {identifier}.{key} 不得为负")
        elif key != "propagation_latency_ms" and value <= 0:
            errors.append(f"[NET-CAPACITY] {identifier}.{key} 必须大于0")


def _facts(errors: list[str], snapshot_checked: bool = False) -> list[dict[str, str]]:
    facts = []
    for rule in describe_satellite_rules():
        key = rule["rule_id"]
        if rule["executor"] == "routing_handler" or (key == "NET-SNAPSHOT" and not snapshot_checked):
            status = "not_evaluated"
        else:
            status = "failed" if any(message.startswith(f"[{key}]") for message in errors) else "passed"
        facts.append({**rule, "status": status})
    return facts


def validate_network_entities(nodes: list[dict[str, Any]], links: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate CSV-shaped entities and endpoint relationships through OWL rules.

    Returns ``ok``, ``errors``, ``typed_entities`` (API-compatible class/payload
    records), ``relations``, ``rule_facts`` and ``checked`` counts. Does not
    mutate the supplied rows or instantiate/persist OWL individuals.
    """
    errors: list[str] = []
    node_rows = _rows(nodes, "nodes", errors)
    link_rows = _rows(links, "links", errors)
    if not node_rows:
        errors.append("[NET-ID] 至少需要一个网络节点")
    entities: list[dict[str, Any]] = []
    relations: list[dict[str, str]] = []
    node_classes: dict[str, str] = {}
    identifiers: set[str] = set()
    for row in node_rows:
        node_id = row.get("node_id", "")
        if not isinstance(node_id, str) or not node_id.strip() or node_id in identifiers:
            errors.append(f"[NET-ID] 节点标识为空、不合法或重复: {node_id}")
            continue
        identifiers.add(node_id)
        node_type = row.get("node_type")
        class_name = {"satellite": "Satellite", "ground_station": "GroundStation"}.get(node_type) if isinstance(node_type, str) else None
        if class_name is None:
            errors.append(f"[NET-TYPE] {node_id}.node_type 仅支持satellite或ground_station")
            continue
        node_classes[node_id] = class_name
        _validate_entity(class_name, node_id, row, _NODE_FIELDS, entities, errors)
        _check_window(row, node_id, "valid_from", "valid_to_exclusive", errors)

    for row in link_rows:
        link_id = row.get("link_id", "")
        if not isinstance(link_id, str) or not link_id.strip() or link_id in identifiers:
            errors.append(f"[NET-ID] 链路标识为空、不合法或重复: {link_id}")
            continue
        identifiers.add(link_id)
        _validate_entity("CommunicationLink", link_id, row, _LINK_FIELDS, entities, errors)
        if not isinstance(row.get("direction"), str) or row["direction"] not in {"directed", "bidirectional"}:
            errors.append(f"[NET-ENDPOINT] {link_id}.direction 仅支持directed或bidirectional")
        source, target = row.get("source_node_id"), row.get("target_node_id")
        if source == target:
            errors.append(f"[NET-ENDPOINT] {link_id} 不允许自环")
        for field, relation_type in (("source_node_id", "LINK_SOURCE"), ("target_node_id", "LINK_TARGET")):
            endpoint = row.get(field)
            if not isinstance(endpoint, str) or endpoint not in node_classes:
                errors.append(f"[NET-ENDPOINT] {link_id}.{field} 未引用合法网络节点")
                continue
            validation = reasoner.validate_relation(relation_type, "CommunicationLink", node_classes[endpoint])
            errors.extend(f"[NET-TYPE] {message}" for message in validation.errors)
            relations.append({"source_id": link_id, "target_id": endpoint, "type": relation_type})
        _check_window(row, link_id, "visible_from", "visible_to_exclusive", errors)

    return {
        "ok": not errors, "errors": errors, "rule_version": RULE_VERSION,
        "typed_entities": entities, "relations": relations,
        "checked": {"nodes": len(node_rows), "links": len(link_rows)},
        "rule_facts": _facts(errors),
        "limitations": ["拓扑校验不等于改路可行：仍需同时验算迁移流量、允许出口和SLA。"],
    }


def validate_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Validate an already-selected snapshot, never silently filter its rows.

    Input: ``nodes``, ``links``, optional ISO ``snapshot_at`` (alias
    ``timestamp``), and ``as_of``. Intervals are half-open [start, end).
    No time supplied means temporal feasibility was NOT evaluated. Supply an
    explicit ``as_of`` to check available_at; missing publication time is then
    reported as unavailable evidence rather than guessed.
    """
    if not isinstance(snapshot, dict):
        result = validate_network_entities([], [])
        result["errors"].append("[NET-TYPE] snapshot 必须是对象")
        result["rule_facts"] = _facts(result["errors"])
        return result
    result = validate_network_entities(snapshot.get("nodes", []), snapshot.get("links", []))
    errors = result["errors"]
    raw_time = snapshot.get("snapshot_at", snapshot.get("timestamp"))
    raw_cutoff = snapshot.get("as_of")
    point = _parse_time(raw_time, "snapshot_at", errors, "NET-SNAPSHOT") if _present(raw_time) else None
    cutoff = _parse_time(raw_cutoff, "as_of", errors, "NET-SNAPSHOT") if _present(raw_cutoff) else None
    rows = [(row, "node_id", "valid_from", "valid_to_exclusive") for row in snapshot.get("nodes", []) if isinstance(row, dict)] if isinstance(snapshot.get("nodes", []), (list, tuple)) else []
    if isinstance(snapshot.get("links", []), (list, tuple)):
        rows.extend((row, "link_id", "visible_from", "visible_to_exclusive") for row in snapshot.get("links", []) if isinstance(row, dict))
    for row, id_field, start_field, end_field in rows:
        label = str(row.get(id_field, "unknown"))
        if point is not None:
            left = _parse_time(row.get(start_field), f"{label}.{start_field}", errors, "NET-SNAPSHOT")
            right = _parse_time(row.get(end_field), f"{label}.{end_field}", errors, "NET-SNAPSHOT")
            if left is not None and right is not None and not left <= point < right:
                errors.append(f"[NET-SNAPSHOT] {label} 在分析时刻不处于有效窗口")
        if cutoff is not None:
            # Valid-from is not publication time; do not invent known-time
            # evidence for static rows that omit available_at.
            known_raw = row.get("available_at")
            if not _present(known_raw):
                result["limitations"].append(f"{label} 缺少available_at，无法验证其证据可知时间。")
                errors.append(f"[NET-SNAPSHOT] {label} 缺少available_at，不能验证证据截止时间")
                continue
            known = _parse_time(known_raw, f"{label}.available_at", errors, "NET-SNAPSHOT")
            if known is not None and known > cutoff:
                errors.append(f"[NET-SNAPSHOT] {label} 在证据截止时间后才可知")
    if not _present(raw_time):
        result["limitations"].append("未提供snapshot_at，未检查分析时刻的节点有效期和链路可见性。")
    if not _present(raw_cutoff):
        result["limitations"].append("未提供as_of，未检查证据可知时间。")
    result["ok"] = not errors
    result["rule_facts"] = _facts(errors, snapshot_checked=_present(raw_time) or _present(raw_cutoff))
    return result
