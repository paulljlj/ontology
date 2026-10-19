"""Only read public observations; no oracle labels or existing DB tests."""
from __future__ import annotations

import copy
import csv
import json
from pathlib import Path

import pytest

from app.application.satellite_routing import optimize_routes, optimize_snapshot
from app.infrastructure.satellite_data import load_case


REAL_DATA = Path(__file__).resolve().parents[2] / "data-output" / "satellite_demo_v1"
STAMP = "2026-09-15T10:00:00+08:00"
AVAILABLE = "2026-09-15T10:01:05+08:00"
END = "2026-09-15T11:00:00+08:00"


def _write_csv(path, rows, fields=None):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def small_data(tmp_path):
    observed = tmp_path / "observed"
    observed.mkdir()
    _write_csv(observed / "cases.csv", [{"case_id": "TEST", "sampling_seconds": 60,
        "sample_start": STAMP, "sample_end_exclusive": END, "analysis_end_exclusive": "2026-09-15T10:01:00+08:00",
        "initial_diagnosis_cutoff": "2026-09-15T10:02:00+08:00"}])
    nodes = [{"node_id": identity, "node_type": "ground_station" if identity == "G" else "satellite",
              "forwarding_capacity_mbps": 100 if identity == "ALT" else 1000,
              "valid_from": STAMP, "valid_to_exclusive": END} for identity in ("S1", "S2", "OLD", "ALT", "G")]
    links = [{"link_id": f"{source}-{target}", "source_node_id": source, "target_node_id": target,
              "direction": "directed", "nominal_capacity_mbps": 1000, "propagation_latency_ms": 1,
              "visible_from": STAMP, "visible_to_exclusive": END}
             for source, target in (("S1", "OLD"), ("S2", "OLD"), ("OLD", "G"),
                                    ("S1", "ALT"), ("S2", "ALT"), ("ALT", "G"))]
    services = [{"service_id": f"V{i}", "source_satellite_id": f"S{i}", "destination_ground_station_id": "G",
                 "allowed_egress_ids": "G", "sla_latency_ms": 150, "sla_availability_pct": 95} for i in (1, 2)]
    routes = [{"case_id": "TEST", "route_id": f"R{i}", "service_id": f"V{i}", "effective_from": STAMP,
               "effective_to_exclusive": END, "available_at": STAMP, "route_status": "active"} for i in (1, 2)]
    hops = [{"case_id": "TEST", "route_id": f"R{i}", "hop_index": j, "node_id": identity,
             "outgoing_link_id": (f"S{i}-OLD" if j == 0 else "OLD-G" if j == 1 else "")}
            for i in (1, 2) for j, identity in enumerate((f"S{i}", "OLD", "G"))]
    traffic = [{"case_id": "TEST", "timestamp": STAMP, "available_at": AVAILABLE,
                "service_id": f"V{i}", "route_id": f"R{i}", "offered_mbps": 40,
                "measurement_status": "observed"} for i in (1, 2)]
    def metric(identity, capacity, ingress, node):
        return {"case_id": "TEST", "timestamp": STAMP, "available_at": AVAILABLE,
                "node_id" if node else "link_id": identity, "effective_capacity_mbps": capacity,
                "ingress_mbps": ingress, "forwarded_mbps" if node else "transmitted_mbps": ingress,
                "measurement_status": "observed", **({} if node else {"operational_state": "UP"})}
    nm = [metric(row["node_id"], row["forwarding_capacity_mbps"],
                 80 if row["node_id"] in ("OLD", "G") else 0 if row["node_id"] == "ALT" else 40, True) for row in nodes]
    lm = [metric(row["link_id"], 1000, 80 if row["link_id"] == "OLD-G" else 40 if row["target_node_id"] == "OLD" else 0, False) for row in links]
    for name, rows in (("nodes", nodes), ("links", links), ("services", services), ("routes", routes),
                       ("route_hops", hops), ("traffic", traffic), ("node_metrics", nm), ("link_metrics", lm)):
        _write_csv(observed / f"{name}.csv", rows)
    _write_csv(observed / "service_metrics.csv", [], ["case_id", "service_id", "timestamp", "available_at", "measurement_status"])
    _write_csv(observed / "events.csv", [], ["case_id", "event_id", "available_at"])
    (tmp_path / "demo_rules.json").write_text("{}", encoding="utf-8")
    return tmp_path


def test_joint_capacity_not_individual_capacity(small_data):
    snapshot = load_case(small_data, "TEST")
    assert optimize_snapshot(snapshot, ["OLD"])["status"] == "feasible"
    snapshot["node_metrics"]["ALT"]["effective_capacity_mbps"] = 80
    # Each 40Mbps service fits 68Mbps headroom by itself; both together do not.
    result = optimize_snapshot(snapshot, ["OLD"])
    assert result["status"] == "no_feasible_route"
    assert not result["proposals"]


def test_shared_destination_capacity_and_latency(small_data):
    snapshot = load_case(small_data, "TEST")
    snapshot["node_metrics"]["G"]["effective_capacity_mbps"] = 90
    assert optimize_snapshot(snapshot, ["OLD"])["status"] == "no_feasible_route"
    snapshot["node_metrics"]["G"]["effective_capacity_mbps"] = 1000
    assert optimize_snapshot(snapshot, ["OLD"], max_latency_ms=2)["status"] == "no_feasible_route"


def test_fixed_ground_endpoint_cannot_be_bypassed(small_data):
    result = optimize_routes(small_data, "TEST", ["G"])
    assert result["status"] == "no_feasible_route"
    assert "Fixed source/allowed destination" in result["reason"]


def test_direction_contact_down_and_missing_are_not_spare_capacity(small_data):
    snapshot = load_case(small_data, "TEST")
    for identity in ("S1-ALT", "S2-ALT"):
        snapshot["link_metrics"][identity]["operational_state"] = "DOWN"
    assert optimize_snapshot(snapshot, ["OLD"])["status"] == "no_feasible_route"
    for identity in ("S1-ALT", "S2-ALT"):
        snapshot["link_metrics"][identity]["operational_state"] = "UP"
        snapshot["links"][identity]["visible_to_exclusive"] = STAMP
    assert optimize_snapshot(snapshot, ["OLD"])["status"] == "no_feasible_route"
    for identity in ("S1-ALT", "S2-ALT"):
        snapshot["links"][identity]["visible_to_exclusive"] = END
        snapshot["links"][identity]["source_node_id"], snapshot["links"][identity]["target_node_id"] = (
            snapshot["links"][identity]["target_node_id"], snapshot["links"][identity]["source_node_id"])
    assert optimize_snapshot(snapshot, ["OLD"])["status"] == "no_feasible_route"


def test_latest_missing_and_future_samples_never_filled(small_data):
    snapshot = load_case(small_data, "TEST")
    snapshot["traffic"]["V1"]["offered_mbps"] = None
    assert optimize_snapshot(snapshot, ["OLD"])["status"] == "insufficient_data"
    snapshot = load_case(small_data, "TEST")
    snapshot["node_metrics"]["ALT"]["available_at"] = "2026-09-15T10:03:00+08:00"
    assert optimize_snapshot(snapshot, ["OLD"])["status"] == "insufficient_data"
    result = optimize_routes(small_data, "TEST", ["OLD"], as_of="2026-09-15T10:00:30+08:00")
    assert result["status"] == "insufficient_data"
    assert "not ended" in result["reason"]


def test_latest_missing_row_retained_by_loader(small_data):
    source = small_data / "observed" / "traffic.csv"
    with source.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    row = {**rows[0], "timestamp": "2026-09-15T10:01:00+08:00", "available_at": "2026-09-15T10:02:05+08:00",
           "offered_mbps": "", "measurement_status": "missing"}
    _write_csv(source, rows + [row])
    snapshot = load_case(small_data, "TEST", at="2026-09-15T10:01:00+08:00", as_of="2026-09-15T10:03:00+08:00")
    assert snapshot["traffic"]["V1"]["offered_mbps"] is None
    assert snapshot["traffic"]["V1"]["measurement_status"] == "missing"


def test_background_traffic_and_returned_inputs_not_mutated(small_data):
    snapshot = load_case(small_data, "TEST")
    snapshot["node_metrics"]["ALT"]["ingress_mbps"] = 20
    snapshot["node_metrics"]["ALT"]["forwarded_mbps"] = 20
    before = copy.deepcopy(snapshot)
    assert optimize_snapshot(snapshot, ["OLD"])["status"] == "no_feasible_route"
    assert snapshot == before


def test_background_not_erased_by_upstream_capacity_loss(small_data):
    snapshot = load_case(small_data, "TEST")
    for identity in ("V1", "V2"):
        snapshot["traffic"][identity]["offered_mbps"] = 80
    snapshot["routes"]["V2"].update(nodes=["S2", "ALT", "G"], links=["S2-ALT", "ALT-G"])
    for identity, cap, ingress, sent in (("S1", 1000, 80, 80), ("S2", 1000, 80, 80),
                                        ("OLD", 100, 60, 60), ("ALT", 1000, 80, 80), ("G", 1000, 140, 140)):
        snapshot["node_metrics"][identity].update(effective_capacity_mbps=cap, ingress_mbps=ingress, forwarded_mbps=sent)
    for identity, cap, ingress, sent in (("S1-OLD", 40, 80, 40), ("S2-OLD", 1000, 0, 0),
                                        ("OLD-G", 1000, 60, 60), ("S1-ALT", 1000, 0, 0),
                                        ("S2-ALT", 1000, 80, 80), ("ALT-G", 1000, 80, 80)):
        snapshot["link_metrics"][identity].update(effective_capacity_mbps=cap, ingress_mbps=ingress, transmitted_mbps=sent)
    # OLD currently gets V1's 40 delivered Mbps plus 20 background. Replacing V1
    # with V2's 80 requires 100Mbps, NOT 80, and exceeds its 85Mbps safety limit.
    result = optimize_snapshot(snapshot, ["S1-OLD", "S2-ALT"])
    assert result["status"] == "no_feasible_route"


def test_missing_propagation_is_not_zero_latency(small_data):
    snapshot = load_case(small_data, "TEST")
    snapshot["links"]["S1-ALT"]["propagation_latency_ms"] = None
    assert optimize_snapshot(snapshot, ["OLD"])["status"] == "insufficient_data"


def test_negative_resource_telemetry_is_insufficient(small_data):
    snapshot = load_case(small_data, "TEST")
    snapshot["node_metrics"]["ALT"].update(ingress_mbps=-10, forwarded_mbps=-10)
    assert optimize_snapshot(snapshot, ["OLD"])["status"] == "insufficient_data"


def test_node_validity_covers_entire_sample(small_data):
    snapshot = load_case(small_data, "TEST")
    snapshot["nodes"]["ALT"]["valid_to_exclusive"] = "2026-09-15T10:00:30+08:00"
    assert optimize_snapshot(snapshot, ["OLD"])["status"] == "no_feasible_route"


def test_missing_route_node_returns_insufficient_not_keyerror(small_data):
    snapshot = load_case(small_data, "TEST")
    del snapshot["nodes"]["G"]
    assert optimize_snapshot(snapshot, ["OLD"])["status"] == "insufficient_data"


def test_no_avoided_routes_is_no_change(small_data):
    assert optimize_routes(small_data, "TEST", [])["status"] == "no_change_needed"


def test_avoid_link_only_moves_its_affected_service(small_data):
    result = optimize_routes(small_data, "TEST", ["S1-OLD"])
    assert result["status"] == "feasible"
    assert result["selected_service_ids"] == ["V1"]
    change = result["proposals"][0]["changes"][0]
    assert change["service_id"] == "V1"
    assert "S1-OLD" not in change["after_links"]


def test_real_case_001_group_reroute_and_existing_risk():
    result = optimize_routes(REAL_DATA, "CASE-001", ["SAT-20"], max_options=1)
    assert result["status"] == "feasible"
    option = result["proposals"][0]
    assert len(option["changes"]) == 10
    assert all(row["after_nodes"][1] == "SAT-21" for row in option["changes"])
    assert all("SAT-20" not in row["after_nodes"] for row in option["changes"])
    assert all(row["estimated_demand_utilization_pct"] <= 85.0001 for row in option["resources"])
    assert any(row["object_id"] == "SAT-24" for row in result["unresolved_risks"])
    assert len(option["service_assessments"]) == 18
    assert all(not row["availability_sla_evaluated"] for row in option["service_assessments"])
    assert not any("estimated_after_availability" in row for row in option["changes"])
    json.dumps(result, allow_nan=False)


def test_real_case_002_ground_fault_and_case_008_missing():
    fixed = optimize_routes(REAL_DATA, "CASE-002", ["GS-01"])
    assert fixed["status"] == "no_feasible_route"
    relay_only = optimize_routes(REAL_DATA, "CASE-002", ["SAT-20"])
    assert relay_only["status"] == "no_feasible_route"
    assert relay_only["blocked_objects"]["GS-01"] == "observed_non_capacity_loss_gt_2pct"
    missing = optimize_routes(REAL_DATA, "CASE-008", ["SAT-20"])
    assert missing["status"] == "insufficient_data"
    assert not missing["proposals"]


def test_evaluation_directory_never_opened(small_data, monkeypatch):
    evaluation = small_data / "evaluation"
    evaluation.mkdir()
    (evaluation / "ground_truth.json").write_text('"DO NOT READ"', encoding="utf-8")
    original = Path.open
    def protected_open(path, *args, **kwargs):
        assert "evaluation" not in path.parts
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", protected_open)
    assert optimize_routes(small_data, "TEST", ["OLD"])["status"] == "feasible"
