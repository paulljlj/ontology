"""OWL-driven validation and Pellet consistency checks."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from owlready2 import (
    AllDifferent,
    FunctionalProperty,
    OwlReadyInconsistentOntologyError,
    Thing,
    TransitiveProperty,
    World,
    sync_reasoner_pellet,
)
from owlready2.class_construct import EXACTLY, MAX, MIN, Restriction

from app.domain import ontology


class ValidationResult:
    def __init__(self, ok: bool, errors: list[str] | None = None):
        self.ok = ok
        self.errors = errors or []

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "errors": self.errors}

    def __bool__(self) -> bool:
        return self.ok


def validate_class(class_name: str) -> ValidationResult:
    if ontology.get_class(class_name) is None:
        return ValidationResult(
            ok=False,
            errors=[f"类「{class_name}」不在本体中。允许的类: {ontology.list_classes()}"],
        )
    return ValidationResult(ok=True)


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _validate_value(field_name: str, value: Any, details: dict[str, Any]) -> str | None:
    kind = details["kind"]
    if _is_empty(value):
        return f"字段「{field_name}」不能为空"
    if kind == "string" and not isinstance(value, str):
        return f"字段「{field_name}」必须是字符串"
    if kind == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
        return f"字段「{field_name}」必须是整数"
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"字段「{field_name}」必须是有限数值"
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            return f"字段「{field_name}」必须是有限数值"
    if kind == "boolean" and not isinstance(value, bool):
        return f"字段「{field_name}」必须是布尔值"
    if kind == "list" and not isinstance(value, list):
        return f"字段「{field_name}」必须是列表"
    if kind == "enum":
        allowed = sorted(instance.name for instance in details["range"].instances())
        if not isinstance(value, str) or value not in allowed:
            return f"字段「{field_name}」值「{value}」不合法，必须是 {allowed} 之一"
    return None


def validate_instance(
    class_name: str,
    title: str,
    status: str,
    properties: dict[str, Any],
) -> ValidationResult:
    class_result = validate_class(class_name)
    if not class_result.ok:
        return class_result

    schema = ontology.get_schema(class_name)
    fields = schema["fields"]
    values = {"title": title, "status": status, **properties}
    errors: list[str] = []

    unknown = sorted(set(values) - set(fields))
    if unknown:
        errors.append(f"「{class_name}」包含本体未声明字段: {unknown}")

    for field_name in schema["required_fields"]:
        if field_name not in values or _is_empty(values[field_name]):
            errors.append(f"「{class_name}」缺少必填字段: {field_name}")

    for field_name, value in values.items():
        details = fields.get(field_name)
        if details is None:
            continue
        if _is_empty(value) and not details["required"]:
            continue
        error = _validate_value(field_name, value, details)
        if error:
            errors.append(f"「{class_name}.{field_name}」{error.split('」', 1)[-1]}")

    return ValidationResult(ok=not errors, errors=errors)


def validate_instance_properties(class_name: str, properties: dict[str, Any]) -> ValidationResult:
    payload = dict(properties)
    title = payload.pop("title", "")
    status = payload.pop("status", "draft")
    return validate_instance(class_name, title, status, payload)


def _class_matches(actual: type, expected: type) -> bool:
    return expected is Thing or expected in actual.ancestors()


def validate_relation(
    relation_type: str,
    source_class: str,
    target_class: str,
) -> ValidationResult:
    schema = ontology.get_relation_schema(relation_type)
    if not schema:
        return ValidationResult(
            ok=False,
            errors=[f"关系「{relation_type}」不在本体中。允许的关系: {ontology.list_relations()}"],
        )

    source = ontology.get_class(source_class)
    target = ontology.get_class(target_class)
    if source is None or target is None:
        invalid = source_class if source is None else target_class
        return validate_class(invalid)

    relation = ontology.onto[relation_type]
    errors: list[str] = []
    if relation.domain and not any(_class_matches(source, expected) for expected in relation.domain):
        errors.append(
            f"关系「{relation_type}」要求 source 是 {[item.name for item in relation.domain]}，但实际是「{source_class}」"
        )
    if relation.range and not any(_class_matches(target, expected) for expected in relation.range):
        errors.append(
            f"关系「{relation_type}」要求 target 是 {[item.name for item in relation.range]}，但实际是「{target_class}」"
        )
    return ValidationResult(ok=not errors, errors=errors)


def describe_class_for_llm(class_name: str) -> str:
    schema = ontology.get_schema(class_name)
    if not schema:
        return f"类「{class_name}」无 OWL 约束。"
    parts = [f"目标类: {class_name}", f"必填字段: {schema['required_fields']}"]
    if schema["optional_fields"]:
        parts.append(f"可选字段: {schema['optional_fields']}")
    for field_name, details in schema["fields"].items():
        if details["kind"] == "enum":
            allowed = sorted(instance.name for instance in details["range"].instances())
            parts.append(f"{field_name} 枚举: {allowed}")
    return "\n".join(parts)


def _safe_name(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", str(value))


def _is_functional(prop: type) -> bool:
    try:
        ancestors = list(prop.ancestors() or [])
    except Exception:
        return False
    return FunctionalProperty in ancestors


def _set_payload_value(individual: Any, prop: type, value: Any, loaded_ontology: Any) -> None:
    if prop is None or getattr(prop, "python_name", None) is None:
        return
    kind_values = getattr(prop, "payload_kind", [])
    kind = kind_values[0] if kind_values else "string"
    if kind == "enum":
        enum_value = loaded_ontology[str(value)]
        if enum_value is None:
            return
        converted = enum_value
    elif kind == "list":
        converted = json.dumps(value, ensure_ascii=False)
    else:
        converted = value

    if _is_functional(prop):
        setattr(individual, prop.python_name, converted)
    else:
        getattr(individual, prop.python_name).append(converted)


def _validate_closed_graph_cardinality(
    loaded_ontology: Any,
    instance_rows: list[dict[str, Any]],
    relation_rows: list[dict[str, Any]],
) -> list[str]:
    outgoing: dict[tuple[str, str], int] = {}
    for relation in relation_rows:
        key = (str(relation["source_id"]), relation["type"])
        outgoing[key] = outgoing.get(key, 0) + 1

    errors: list[str] = []
    for (source_id, relation_type), count in outgoing.items():
        prop = loaded_ontology[relation_type]
        if _is_functional(prop) and count > 1:
            errors.append(
                f"实例「{source_id}」的函数关系「{relation_type}」最多允许 1 条，实际 {count} 条"
            )

    for row in instance_rows:
        owl_class = loaded_ontology[row["class_name"]]
        for ancestor in owl_class.ancestors():
            for restriction in ancestor.is_a:
                if not isinstance(restriction, Restriction):
                    continue
                prop = restriction.property
                if getattr(prop, "payload_field", []):
                    continue
                count = outgoing.get((str(row["id"]), prop.name), 0)
                if restriction.type in (MIN, EXACTLY) and count < restriction.cardinality:
                    errors.append(
                        f"实例「{row['id']}」关系「{prop.name}」至少需要 {restriction.cardinality} 条，实际 {count} 条"
                    )
                if restriction.type in (MAX, EXACTLY) and count > restriction.cardinality:
                    errors.append(
                        f"实例「{row['id']}」关系「{prop.name}」最多允许 {restriction.cardinality} 条，实际 {count} 条"
                    )
    return errors


def validate_with_pellet(
    instances: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    owl_path: str | Path = ontology.DEFAULT_OWL_PATH,
) -> ValidationResult:
    path = Path(owl_path)
    if not path.exists():
        ontology.export_ontology(path)

    world = World()
    loaded = world.get_ontology(str(path.resolve())).load()
    errors = _validate_closed_graph_cardinality(loaded, instances, relations)
    if errors:
        world.close()
        return ValidationResult(ok=False, errors=errors)

    individuals: dict[str, Any] = {}
    try:
        for row in instances:
            properties = dict(row.get("properties") or {})
            fast_result = validate_instance(
                row["class_name"],
                row.get("title", ""),
                row.get("status", "draft"),
                properties,
            )
            if not fast_result.ok:
                return fast_result

            owl_class = loaded[row["class_name"]]
            individual = owl_class(f"validation_{_safe_name(row['id'])}")
            individuals[str(row["id"])] = individual
            values = {"title": row.get("title", ""), "status": row.get("status", "draft"), **properties}
            for field_name, value in values.items():
                if _is_empty(value):
                    continue
                _set_payload_value(individual, loaded[field_name], value, loaded)

        if len(individuals) > 1:
            with loaded:
                AllDifferent(list(individuals.values()))

        for row in relations:
            source = individuals[str(row["source_id"])]
            target = individuals[str(row["target_id"])]
            prop = loaded[row["type"]]
            if _is_functional(prop):
                setattr(source, prop.python_name, target)
            else:
                getattr(source, prop.python_name).append(target)

        sync_reasoner_pellet(
            [loaded],
            infer_property_values=True,
            infer_data_property_values=True,
            debug=0,
        )
    except OwlReadyInconsistentOntologyError as exc:
        return ValidationResult(ok=False, errors=[f"Pellet 检测到本体不一致: {exc}"])
    except Exception as exc:
        return ValidationResult(ok=False, errors=[f"Pellet 推理失败: {exc}"])
    finally:
        world.close()

    return ValidationResult(ok=True)


def compute_inferred_edges(
    instances: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    owl_path: str | Path = ontology.DEFAULT_OWL_PATH,
) -> list[dict[str, Any]]:
    """Materialize inferred (non-asserted) edges by running Pellet in a sandboxed World.

    Returns a list of edges that are NOT in the asserted ``relations`` list, each shaped
    like ``{source_id, target_id, type, reason}``. Only relations whose property is
    transitive (or sub-property of a transitive one) are considered; functional /
    symmetric / reflexive closures are skipped to avoid trivial noise.
    """
    path = Path(owl_path)
    if not path.exists():
        ontology.export_ontology(path)

    asserted_pairs = {
        (str(rel["source_id"]), str(rel["target_id"]), rel["type"])
        for rel in relations
    }
    id_to_individual: dict[str, Any] = {}
    inferred: list[dict[str, Any]] = []

    world = World()
    try:
        loaded = world.get_ontology(str(path.resolve())).load()

        for row in instances:
            owl_class = loaded[row["class_name"]]
            individual = owl_class(f"infer_{_safe_name(row['id'])}")
            id_to_individual[str(row["id"])] = individual
            values = {
                "title": row.get("title", ""),
                "status": row.get("status", "draft"),
                **(row.get("properties") or {}),
            }
            for field_name, value in values.items():
                if _is_empty(value):
                    continue
                _set_payload_value(individual, loaded[field_name], value, loaded)

        if len(id_to_individual) > 1:
            with loaded:
                AllDifferent(list(id_to_individual.values()))

        for rel in relations:
            source = id_to_individual[str(rel["source_id"])]
            target = id_to_individual[str(rel["target_id"])]
            prop = loaded[rel["type"]]
            if _is_functional(prop):
                setattr(source, prop.python_name, target)
            else:
                getattr(source, prop.python_name).append(target)

        sync_reasoner_pellet(
            [loaded],
            infer_property_values=True,
            infer_data_property_values=True,
            debug=0,
        )

        individual_to_id = {individual: sid for sid, individual in id_to_individual.items()}
        transitive_names = _transitive_relation_names()
        for prop in loaded.object_properties():
            name = prop.name
            if not name or name not in transitive_names:
                continue
            for source, target in prop.get_relations():
                sid = individual_to_id.get(source)
                tid = individual_to_id.get(target)
                if sid is None or tid is None or sid == tid:
                    continue
                if (sid, tid, name) in asserted_pairs:
                    continue
                inferred.append(
                    {
                        "source_id": sid,
                        "target_id": tid,
                        "type": name,
                        "reason": "transitive_closure",
                    }
                )
    finally:
        world.close()

    return inferred


def _transitive_relation_names() -> set[str]:
    """Names of object properties that are (or are sub-properties of) TransitiveProperty.

    Owlready2 attaches TransitiveProperty to ``is_a`` rather than ``ancestors()``,
    so we look at the in-process ontology's ``is_a`` and then map back to names.
    """
    names: set[str] = set()
    for prop in ontology.onto.object_properties():
        try:
            is_a = list(prop.is_a or [])
        except Exception:
            is_a = []
        if TransitiveProperty in is_a:
            names.add(prop.name)
    return names


def _is_transitive_or_sub(prop: type) -> bool:
    transitive = _transitive_relation_names()
    return prop.name in transitive
