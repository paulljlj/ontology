"""Adapter from the collaborator's diagnostic report to the workflow contract.

The diagnostic package keeps its richer schema 1.1 and its minute-level audit
trail.  The workflow only receives a bounded, validated summary so large raw
reports are not copied into the run request or database summary.
"""
from __future__ import annotations

from datetime import timedelta
import hashlib
from typing import Any, Iterable

from app.domain.satellite_schemas import DiagnosisInput
from app.infrastructure.satellite_data import parse_time
from satellite_diagnosis import LocalGraph, analyze_case, load_case as load_diagnosis_case


OBSERVED_SOURCES = {
    "events", "link_metrics", "node_metrics", "route_hops", "routes",
    "service_metrics", "services", "traffic",
}


def _iter_evidence(value: Any) -> Iterable[dict[str, Any]]:
    """Yield evidence-shaped dictionaries from nested report fragments."""
    if isinstance(value, list):
        for item in value:
            yield from _iter_evidence(item)
        return
    if not isinstance(value, dict):
        return
    required = {"source", "record_id", "object_id", "timestamp", "available_at"}
    if required <= value.keys() and value.get("source") in OBSERVED_SOURCES:
        yield value
    for item in value.values():
        if isinstance(item, (dict, list)):
            yield from _iter_evidence(item)


def _evidence_key(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(row.get(key) or "") for key in (
        "source", "record_id", "object_id", "field", "timestamp", "available_at",
    ))


def _evidence_id(row: dict[str, Any]) -> str:
    digest = hashlib.sha256("\x1f".join(_evidence_key(row)).encode("utf-8")).hexdigest()[:20]
    return f"DIAG-{digest}"


def _visible_evidence(row: dict[str, Any], *, at, as_of) -> bool:
    try:
        return parse_time(str(row["timestamp"])) <= at and parse_time(str(row["available_at"])) <= as_of
    except (KeyError, TypeError, ValueError):
        return False


def _compact_watch(raw: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    groups = (("watch", "需要关注"), ("observing", "继续观察"))
    for key, label in groups:
        for item in raw.get(key, []):
            service = item.get("service", item)
            result.append({
                "service_id": item.get("service_id") or service.get("service_id"),
                "classification": service.get("classification", key),
                "status_label": label,
                "baseline_availability_pct": service.get("baseline_availability_pct"),
                "analysis_mean_availability_pct": service.get("analysis_mean_availability_pct"),
                "mean_drop_pp": service.get("mean_drop_pp"),
                "peak_drop_pp": service.get("peak_drop_pp"),
                "longest_contiguous_minutes": service.get("longest_contiguous_minutes"),
                "first_decline_at": service.get("first_decline_at"),
                "supporting_resource": item.get("supporting_resource"),
                "note": "关注项不是已确认故障；计划切换和缺测会单独保留。",
            })
    return result


def adapt_diagnosis_report(raw: dict[str, Any], snapshot: dict[str, Any]) -> DiagnosisInput:
    """Convert schema 1.1 into the stable DiagnosisInput 1.0 contract."""
    if raw.get("schema_version") != "1.1" or raw.get("case_id") != snapshot["case"]["case_id"]:
        raise ValueError("同学诊断结果的版本或案例编号不匹配")
    at = parse_time(snapshot["at"])
    as_of = parse_time(str(raw["as_of"]))
    sample_end = at + timedelta(seconds=float(snapshot["sampling_seconds"]))

    evidence_rows: dict[tuple[str, ...], dict[str, Any]] = {}
    candidates = list(raw.get("root_cause_candidates", []))
    minor = dict(raw.get("minor_anomalies", {}))
    conclusion = dict(raw.get("conclusion_and_missing_evidence", {}))
    for fragment in (candidates, minor, conclusion.get("basis", [])):
        for row in _iter_evidence(fragment):
            if _visible_evidence(row, at=at, as_of=as_of):
                evidence_rows.setdefault(_evidence_key(row), row)

    converted_evidence = []
    ids: dict[tuple[str, ...], str] = {}
    for key, row in evidence_rows.items():
        identity = _evidence_id(row)
        ids[key] = identity
        field = str(row.get("field") or "observation")
        value = row.get("value")
        unit = str(row.get("unit") or "")
        converted_evidence.append({
            "evidence_id": identity,
            "object_id": str(row["object_id"]),
            "timestamp": row["timestamp"],
            "available_at": row["available_at"],
            "source_file": f"observed/{row['source']}.csv",
            "record_id": str(row["record_id"]),
            "description": f"{field}={value}{(' ' + unit) if unit else ''}",
        })
    if len(converted_evidence) > 2000:
        raise ValueError("诊断证据超过工作流契约上限，不能静默截断引用")

    priority = conclusion.get("priority_object")
    converted_causes = []
    known_nodes = snapshot["nodes"]
    known_links = snapshot["links"]
    for candidate in candidates:
        object_id = str(candidate.get("object_id") or "")
        if object_id in known_links:
            object_type = "link"
        elif object_id in known_nodes:
            object_type = known_nodes[object_id]["node_type"]
        else:
            raise ValueError(f"同学诊断包含未知对象：{object_id}")
        supporting = [ids[_evidence_key(row)] for row in _iter_evidence(candidate.get("supporting_evidence", []))
                      if _evidence_key(row) in ids]
        contradicting = [ids[_evidence_key(row)] for row in _iter_evidence(candidate.get("counter_evidence", []))
                         if _evidence_key(row) in ids]
        strength = candidate.get("evidence_strength")
        status = "supported" if object_id == priority and strength == "multi_signal" and supporting else (
            "candidate" if supporting or contradicting else "insufficient_evidence"
        )
        converted_causes.append({
            "object_id": object_id,
            "object_type": object_type,
            "mechanism": str(candidate.get("hypothesis") or "共享依赖，需要补充独立遥测证据")[:240],
            "status": status,
            "supporting_evidence_ids": list(dict.fromkeys(supporting)),
            "contradicting_evidence_ids": list(dict.fromkeys(contradicting)),
            "missing_evidence": [str(item)[:500] for item in candidate.get("missing_evidence", [])[:100]],
        })

    impact = dict(raw.get("impact_and_controls", {}))
    impact_items = [{
        "title": "受影响与正常业务对照",
        "affected_service_ids": impact.get("affected_service_ids", []),
        "healthy_service_ids": impact.get("healthy_service_ids", []),
    }]
    impact_items.extend(dict(item) for item in impact.get("candidate_controls", [])[:50])

    data_quality = dict(raw.get("data_quality", {}))
    missing = [str(item) for item in conclusion.get("next_evidence", [])]
    if data_quality.get("unobserved_service_ids"):
        missing.append("未观测业务：" + "、".join(data_quality["unobserved_service_ids"]))
    if data_quality.get("baseline_missing_services"):
        missing.append("缺少基线的业务：" + "、".join(data_quality["baseline_missing_services"]))
    if data_quality.get("telemetry_gaps"):
        missing.append("部分候选存在遥测缺口，详见完整诊断产物。")

    window = raw.get("analysis_window", {})
    analysis_end = min(parse_time(str(window.get("to_exclusive"))), sample_end, as_of)
    conclusions = []
    if priority:
        conclusions.append(f"优先排查 {priority}：{conclusion.get('assessment', '需要继续核实')}。")
    else:
        conclusions.append(str(conclusion.get("assessment") or "未确认持续重大异常，继续观察。"))
    conclusions.append("候选排序来自共同依赖、容量/设备指标、告警时序和正常对照；不是已校准故障概率。")

    overview = dict(raw.get("anomaly_overview", {}))
    overview.pop("all_service_statuses", None)
    overview.update({
        "provider": "collaborator_satellite_diagnosis",
        "provider_schema_version": raw["schema_version"],
        "graph_backend": raw.get("graph_backend"),
        "analysis_window": window,
        "data_quality_summary": {
            "unobserved_service_ids": data_quality.get("unobserved_service_ids", []),
            "service_missing_minutes": data_quality.get("service_missing_minutes", 0),
            "capacity_incomplete_count": len(data_quality.get("capacity_completeness", [])),
        },
    })

    return DiagnosisInput.model_validate({
        "schema_version": "1.0",
        "case_id": raw["case_id"],
        "analysis_start": window.get("from"),
        "analysis_end": analysis_end.isoformat(),
        "as_of": raw["as_of"],
        "source": "external_diagnosis",
        "overview": overview,
        "causes": converted_causes,
        "watch_items": _compact_watch(minor),
        "impact": impact_items,
        "conclusions": conclusions,
        "missing_evidence": list(dict.fromkeys(missing))[:100],
        "evidence": converted_evidence,
    })


def run_integrated_diagnosis(data_root, snapshot: dict[str, Any], *, graph_backend: str = "local"):
    """Run the delivered module and return both bounded contract and full audit report."""
    case_id = snapshot["case"]["case_id"]
    if graph_backend == "local":
        loaded = load_diagnosis_case(data_root, case_id, snapshot["as_of"], snapshot["at"])
        graph = LocalGraph(loaded["tables"])
    elif graph_backend == "neo4j_mcp":
        graph = None
    else:
        raise ValueError("diagnosis_graph_backend必须为local或neo4j_mcp")
    raw = analyze_case(data_root, case_id, cutoff=snapshot["as_of"], graph=graph,
        observation_at=snapshot["at"])
    diagnosis = adapt_diagnosis_report(raw, snapshot)
    return diagnosis, raw
