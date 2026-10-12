from __future__ import annotations

import os
from pathlib import Path

TEST_DB = Path("test_ontology.db")
if TEST_DB.exists():
    TEST_DB.unlink()

os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{TEST_DB}"

from owlready2 import FunctionalProperty  # noqa: E402

from app.domain import ontology, reasoner  # noqa: E402
from app.domain.constants import ClassName, RelationType  # noqa: E402
from app.domain.reasoner import Restriction  # noqa: E402


def test_classes_and_relations_are_exposed():
    classes = ontology.list_classes()
    assert {"Project", "Feature", "Spec", "Plan", "Task"}.issubset(classes)
    assert ontology.get_class("Feature") is not None
    assert ontology.get_class("NotAClass") is None

    relations = ontology.list_relations()
    assert {RelationType.DERIVES_TO, RelationType.HAS_PLAN, RelationType.HAS_TASK}.issubset(relations)


def test_schema_derives_required_and_enums():
    schema = ontology.get_schema(ClassName.FEATURE)
    assert "title" in schema["required_fields"]
    assert "priority" in schema["optional_fields"]
    assert set(schema["priority_enum"]) == {"low", "medium", "high", "critical"}

    plan_schema = ontology.get_schema(ClassName.PLAN)
    assert "summary" in plan_schema["required_fields"]

    task_schema = ontology.get_schema(ClassName.TASK)
    assert set(task_schema["layer_enum"]) == {"domain", "application", "api", "infrastructure", "test"}


def test_cardinality_restrictions_are_declared():
    plan_class = ontology.get_class(ClassName.PLAN)
    plan_is_a = list(plan_class.is_a)
    has_task = ontology.onto[RelationType.HAS_TASK]
    found = False
    for restriction in plan_is_a:
        if not isinstance(restriction, Restriction):
            continue
        if restriction.property is has_task and getattr(restriction, "cardinality", 0) >= 1:
            found = True
            break
    assert found


def test_derives_to_is_functional():
    relation = ontology.onto[RelationType.DERIVES_TO]
    assert FunctionalProperty in relation.is_a


def test_validate_instance_accepts_and_rejects():
    ok = reasoner.validate_instance(
        ClassName.FEATURE,
        title="演示需求",
        status="idea",
        properties={"priority": "high"},
    )
    assert ok.ok

    missing = reasoner.validate_instance(
        ClassName.FEATURE,
        title="",
        status="idea",
        properties={},
    )
    assert not missing.ok

    bad_enum = reasoner.validate_instance(
        ClassName.FEATURE,
        title="演示需求",
        status="idea",
        properties={"priority": "frontend"},
    )
    assert not bad_enum.ok

    unknown = reasoner.validate_instance(
        ClassName.FEATURE,
        title="演示需求",
        status="idea",
        properties={"unknown_field": "value"},
    )
    assert not unknown.ok


def test_validate_relation_domain_range():
    ok = reasoner.validate_relation(RelationType.HAS_TASK, ClassName.PLAN, ClassName.TASK)
    assert ok.ok

    bad = reasoner.validate_relation(RelationType.HAS_TASK, ClassName.FEATURE, ClassName.JENKINS_JOB)
    assert not bad.ok


def test_validate_with_pellet_passes_for_consistent_graph():
    result = reasoner.validate_with_pellet(
        instances=[
            {"id": "f1", "class_name": "Feature", "title": "演示", "status": "idea", "properties": {"priority": "high"}},
            {"id": "s1", "class_name": "Spec", "title": "规格", "status": "ready", "properties": {"goal": "目标"}},
            {"id": "p1", "class_name": "Plan", "title": "计划", "status": "ready", "properties": {"summary": "概要"}},
            {"id": "t1", "class_name": "Task", "title": "任务", "status": "todo", "properties": {"layer": "application"}},
        ],
        relations=[
            {"id": "r1", "source_id": "f1", "target_id": "s1", "type": "DERIVES_TO", "properties": {}},
            {"id": "r2", "source_id": "s1", "target_id": "p1", "type": "HAS_PLAN", "properties": {}},
            {"id": "r3", "source_id": "p1", "target_id": "t1", "type": "HAS_TASK", "properties": {}},
        ],
    )
    assert result.ok, result.errors


def test_validate_with_pellet_rejects_functional_violation():
    result = reasoner.validate_with_pellet(
        instances=[
            {"id": "f1", "class_name": "Feature", "title": "演示", "status": "idea", "properties": {}},
            {"id": "s1", "class_name": "Spec", "title": "规格1", "status": "ready", "properties": {"goal": "目标1"}},
            {"id": "s2", "class_name": "Spec", "title": "规格2", "status": "ready", "properties": {"goal": "目标2"}},
        ],
        relations=[
            {"id": "r1", "source_id": "f1", "target_id": "s1", "type": "DERIVES_TO", "properties": {}},
            {"id": "r2", "source_id": "f1", "target_id": "s2", "type": "DERIVES_TO", "properties": {}},
        ],
    )
    assert not result.ok
    assert any("DERIVES_TO" in error for error in result.errors)