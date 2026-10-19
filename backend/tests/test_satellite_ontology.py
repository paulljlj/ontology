"""Isolated domain tests: no DB config, fixed-file deletion, services or Pellet."""
from __future__ import annotations

from copy import deepcopy

import pytest
from owlready2 import World

from app.domain import ontology, reasoner
from app.domain.constants import ClassName, RelationType
from app.domain.satellite_rules import (
    describe_satellite_rules,
    validate_network_entities,
    validate_snapshot,
)


def network_rows():
    return [
        {"node_id": "SAT-01", "node_type": "satellite", "constellation": "GROUP-1",
         "forwarding_capacity_mbps": "500", "nominal_bus_voltage_v": "28",
         "valid_from": "2026-09-15T09:30:00+08:00", "valid_to_exclusive": "2026-09-15T11:31:00+08:00",
         "available_at": "2026-09-15T09:00:00+08:00", "provenance": "synthetic"},
        {"node_id": "GS-01", "node_type": "ground_station", "forwarding_capacity_mbps": "2500",
         "valid_from": "2026-09-15T09:30:00+08:00", "valid_to_exclusive": "2026-09-15T11:31:00+08:00",
         "available_at": "2026-09-15T09:00:00+08:00"},
    ], [
        {"link_id": "L-1", "source_node_id": "SAT-01", "target_node_id": "GS-01",
         "direction": "directed", "link_type": "satellite_ground", "nominal_capacity_mbps": "400",
         "propagation_latency_ms": "12.18", "visible_from": "2026-09-15T09:30:00+08:00",
         "visible_to_exclusive": "2026-09-15T11:31:00+08:00", "available_at": "2026-09-15T09:00:00+08:00"},
    ]


def test_concrete_classes_and_automatic_enums_exclude_abstract_roots():
    expected = {"Satellite", "GroundStation", "CommunicationLink", "Route", "NetworkService",
                "MetricObservation", "AlarmEvent", "RouteProposal", "NetworkSnapshot"}
    assert expected.issubset(ontology.list_classes())
    assert "NetworkEntity" not in ontology.list_classes()
    assert "NetworkNode" not in ontology.list_classes()
    assert ontology.get_class("NetworkNode") is None
    assert ClassName.SATELLITE == "Satellite"
    assert ClassName.ROUTE_PROPOSAL == "RouteProposal"
    assert RelationType.ROUTE_USES_NODE == "ROUTE_USES_NODE"
    assert ontology.onto.NetworkNode in ontology.onto.Satellite.ancestors()
    # Neither abstract ancestor may appear in a disjoint concrete class set.
    for declaration in ontology.onto.disjoint_classes():
        assert ontology.onto.NetworkNode not in declaration.entities
        assert ontology.onto.NetworkEntity not in declaration.entities


def test_inherited_fields_and_number_schema_are_real_owl_constraints():
    schema = ontology.get_schema("Satellite")
    assert {"title", "external_id", "node_type"}.issubset(schema["required_fields"])
    assert schema["fields"]["forwarding_capacity_mbps"]["kind"] == "number"
    assert ontology.get_schema("CommunicationLink")["fields"]["nominal_capacity_mbps"]["required"]
    assert not reasoner.validate_instance("Satellite", "S", "active", {"node_type": "satellite"}).ok
    assert not reasoner.validate_instance("Satellite", "S", "active", {
        "external_id": "S", "node_type": "satellite", "made_up_field": 1,
    }).ok


@pytest.mark.parametrize("value", [True, False, float("nan"), float("inf"), float("-inf"), "400", 10 ** 400])
def test_number_validation_rejects_bool_nonfinite_and_non_numeric(value):
    result = reasoner.validate_instance("Satellite", "S", "active", {
        "external_id": "S", "node_type": "satellite", "forwarding_capacity_mbps": value,
    })
    assert not result.ok
    assert any("有限数值" in error for error in result.errors)


@pytest.mark.parametrize("value", [0, 1, 1.25])
def test_number_schema_accepts_finite_int_or_float(value):
    # Positivity is a planning rule, separate from OWL payload type checking.
    assert reasoner.validate_instance("Satellite", "S", "active", {
        "external_id": "S", "node_type": "satellite", "forwarding_capacity_mbps": value,
    }).ok


def test_relation_domains_and_ranges_use_single_abstract_parent():
    assert reasoner.validate_relation("ROUTE_USES_NODE", "Route", "Satellite").ok
    assert reasoner.validate_relation("ROUTE_USES_NODE", "Route", "GroundStation").ok
    assert not reasoner.validate_relation("ROUTE_USES_NODE", "Route", "CommunicationLink").ok
    assert not reasoner.validate_relation("LINK_SOURCE", "Satellite", "GroundStation").ok
    assert reasoner.validate_relation("PROPOSAL_FOR_SERVICE", "RouteProposal", "NetworkService").ok
    for name in ("ROUTE_USES_NODE", "ROUTE_USES_LINK", "SERVICE_USES_ROUTE", "LINK_SOURCE",
                 "LINK_TARGET", "OBSERVES_ENTITY", "ALARM_ON_ENTITY", "SNAPSHOT_CONTAINS", "PROPOSAL_FOR_SERVICE"):
        schema = ontology.get_relation_schema(name)
        assert len(schema["domain"]) == len(schema["range"]) == 1


def test_new_ontology_exports_only_to_temporary_file(tmp_path):
    path = ontology.export_ontology(tmp_path / "satellite-test.owl")
    world = World()
    try:
        loaded = world.get_ontology(str(path.resolve())).load()
        assert loaded.Satellite is not None
        assert loaded.NetworkNode in loaded.Satellite.ancestors()
        assert loaded.ROUTE_USES_NODE.range == [loaded.NetworkNode]
        assert loaded.nominal_capacity_mbps.payload_kind == ["number"]
        assert loaded.NetworkNode.instantiable == []
    finally:
        world.close()


def test_committed_owl_snapshot_contains_satellite_schema():
    # Pellet's default path must not be a stale snapshot of the old schema.
    world = World()
    try:
        loaded = world.get_ontology(str(ontology.DEFAULT_OWL_PATH.resolve())).load()
        assert loaded.Satellite is not None
        assert loaded.NetworkSnapshot is not None
        assert loaded.LINK_SOURCE.range == [loaded.NetworkNode]
        assert loaded.nominal_capacity_mbps.payload_kind == ["number"]
    finally:
        world.close()


def test_csv_entities_are_typed_validated_without_mutating_inputs():
    nodes, links = network_rows()
    original = deepcopy((nodes, links))
    result = validate_network_entities(nodes, links)
    assert result["ok"], result["errors"]
    assert (nodes, links) == original
    assert result["checked"] == {"nodes": 2, "links": 1}
    link = next(entity for entity in result["typed_entities"] if entity["class_name"] == "CommunicationLink")
    assert link["properties"]["nominal_capacity_mbps"] == 400.0
    assert len(result["relations"]) == 2
    assert next(fact for fact in result["rule_facts"] if fact["rule_id"] == "PLAN-LOAD")["status"] == "not_evaluated"
    assert next(fact for fact in result["rule_facts"] if fact["rule_id"] == "NET-SNAPSHOT")["status"] == "not_evaluated"


def test_invalid_identifiers_endpoints_capacity_and_time_are_rejected():
    nodes, links = network_rows()
    nodes.append(deepcopy(nodes[0]))
    links[0].update({"target_node_id": "UNKNOWN", "nominal_capacity_mbps": "0",
                     "propagation_latency_ms": "-1", "visible_to_exclusive": "2026-09-15T09:00:00+08:00"})
    result = validate_network_entities(nodes, links)
    assert not result["ok"]
    for rule in ("NET-ID", "NET-ENDPOINT", "NET-CAPACITY", "NET-TIME"):
        assert any(error.startswith(f"[{rule}]") for error in result["errors"])


def test_malformed_container_and_type_values_fail_without_crashing():
    assert not validate_network_entities({}, [None])["ok"]
    nodes, links = network_rows()
    nodes[0]["node_type"] = {}
    links[0]["direction"] = []
    assert not validate_network_entities(nodes, links)["ok"]
    assert not validate_snapshot([])["ok"]


def test_snapshot_checks_half_open_window_and_evidence_cutoff():
    nodes, links = network_rows()
    snapshot = {"nodes": nodes, "links": links, "snapshot_at": "2026-09-15T10:00:00+08:00",
                "as_of": "2026-09-15T10:05:00+08:00"}
    assert validate_snapshot(snapshot)["ok"]
    snapshot["snapshot_at"] = "2026-09-15T11:31:00+08:00"
    assert not validate_snapshot(snapshot)["ok"]
    snapshot["snapshot_at"] = "2026-09-15T10:00:00+08:00"
    links[0]["available_at"] = "2026-09-15T10:06:00+08:00"
    assert any("截止时间后" in error for error in validate_snapshot(snapshot)["errors"])


def test_missing_known_time_is_not_replaced_by_valid_from():
    nodes, links = network_rows()
    del nodes[0]["available_at"]
    result = validate_snapshot({"nodes": nodes, "links": links, "as_of": "2026-09-15T10:05:00+08:00"})
    assert not result["ok"]
    assert any("缺少available_at" in error for error in result["errors"])


def test_existing_software_payload_rules_remain_unchanged():
    assert reasoner.validate_instance("Feature", "需求", "idea", {"priority": "high"}).ok
    assert not reasoner.validate_instance("Feature", "需求", "idea", {"priority": "standard"}).ok
    assert reasoner.validate_relation("HAS_TASK", "Plan", "Task").ok
    assert any(rule["rule_id"] == "PLAN-SLA" for rule in describe_satellite_rules())
