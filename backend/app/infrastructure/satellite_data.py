"""Read-only, time-aware access to the public synthetic observation files.

Only the explicitly named observation CSVs and demo_rules.json are read.  The
evaluation directory, manifest, README, and generator are never model inputs.
"""
from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


OBSERVATION_TABLES = (
    "cases", "nodes", "links", "services", "routes", "route_hops", "traffic",
    "node_metrics", "link_metrics", "service_metrics", "events",
)
NUMERIC_FIELDS = {
    "sampling_seconds", "hop_index", "forwarding_capacity_mbps", "nominal_bus_voltage_v",
    "nominal_capacity_mbps", "propagation_latency_ms", "sla_latency_ms", "sla_availability_pct",
    "probe_attempts_per_minute", "baseline_offered_mbps", "offered_mbps", "effective_capacity_mbps",
    "ingress_mbps", "forwarded_mbps", "transmitted_mbps", "discarded_mbps",
    "demand_utilization_pct", "forwarding_utilization_pct", "queue_depth_mb", "cpu_utilization_pct",
    "temperature_c", "bus_voltage_v", "radiation_proxy_counts_per_min", "seu_events_per_min",
    "ecc_corrected_events_per_min", "reset_events_per_min", "probe_attempts", "probe_successes",
    "availability_pct", "delivered_mbps", "packet_loss_pct", "mean_latency_ms", "snr_db", "bit_error_rate",
}


class SatelliteDataError(ValueError):
    """The observations cannot support the requested snapshot."""


def parse_time(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise SatelliteDataError(f"Invalid ISO timestamp: {value!r}") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise SatelliteDataError("Timestamps must include an explicit UTC offset")
    return result


def _safe_file(root: Path, relative: str) -> Path:
    allowed = {f"observed/{name}.csv" for name in OBSERVATION_TABLES} | {"demo_rules.json"}
    if relative not in allowed:
        raise SatelliteDataError("File is not in the observation allowlist")
    target = (root / relative).resolve()
    try:
        resolved_relative = target.relative_to(root)
    except ValueError as exc:
        raise SatelliteDataError("Observation path escapes the dataset directory") from exc
    if resolved_relative.as_posix() != relative:
        raise SatelliteDataError("Observation aliases/symlinks to other files are not allowed")
    if not target.is_file():
        raise SatelliteDataError(f"Missing observation file: {relative}")
    return target


def _typed(row: dict[str, str]) -> dict[str, Any]:
    result: dict[str, Any] = dict(row)
    for key in NUMERIC_FIELDS.intersection(row):
        value = row[key]
        if not value.strip():
            result[key] = None
            continue
        try:
            number = float(value)
        except ValueError as exc:
            raise SatelliteDataError(f"Invalid numeric observation {key}={value!r}") from exc
        if not math.isfinite(number):
            raise SatelliteDataError(f"Non-finite numeric observation: {key}")
        result[key] = number
    return result


def _csv_rows(root: Path, name: str, case_id: str | None = None):
    with _safe_file(root, f"observed/{name}.csv").open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            if case_id is None or "case_id" not in row or row["case_id"] == case_id:
                yield row


def _visible(row: dict[str, str], at: datetime, cutoff: datetime, sampling: float) -> bool:
    available = row.get("available_at")
    if available and parse_time(available) > cutoff:
        return False
    if row.get("timestamp"):
        stamp = parse_time(row["timestamp"])
        return stamp <= at and stamp + timedelta(seconds=sampling) <= cutoff
    return True


def _latest(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        identity = row[key]
        previous = result.get(identity)
        # Deliberately retain a newest missing observation, not an older good one.
        order = (parse_time(row["timestamp"]), parse_time(row["available_at"]))
        if previous is None or order > (parse_time(previous["timestamp"]), parse_time(previous["available_at"])):
            result[identity] = row
    return result


def load_case(data_root: Path, case_id: str, *, at: str | None = None, as_of: str | None = None) -> dict[str, Any]:
    """Return visible history plus indexed current observations for one case.

    Keys: case/rules/at/as_of; nodes/links/services indexed by ID; routes indexed
    by service ID (each route includes ordered nodes and links); traffic and
    *_metrics indexed by object ID; events; tables with visible histories;
    evidence/limitations. Numeric CSV cells become float or None. All returned
    timestamps retain ISO strings. No future observation or missing-value fill.
    """
    root = Path(data_root).resolve()
    matches = [row for row in _csv_rows(root, "cases") if row["case_id"] == case_id]
    if len(matches) != 1:
        raise SatelliteDataError(f"Unknown or duplicated case_id: {case_id}")
    case = _typed(matches[0])
    sampling = float(case.get("sampling_seconds") or 60)
    if sampling <= 0:
        raise SatelliteDataError("sampling_seconds must be positive")
    target = parse_time(at) if at else parse_time(case["analysis_end_exclusive"]) - timedelta(seconds=sampling)
    cutoff = parse_time(as_of or case["initial_diagnosis_cutoff"])
    if target + timedelta(seconds=sampling) > cutoff:
        raise SatelliteDataError("Requested sample has not ended at as_of")
    if not parse_time(case["sample_start"]) <= target < parse_time(case["sample_end_exclusive"]):
        raise SatelliteDataError("at lies outside the case observation interval")
    tables: dict[str, list[dict[str, Any]]] = {"cases": [case]}
    for name in OBSERVATION_TABLES[1:]:
        tables[name] = [_typed(row) for row in _csv_rows(root, name, case_id)
                        if _visible(row, target, cutoff, sampling)]
    with _safe_file(root, "demo_rules.json").open(encoding="utf-8") as source:
        rules = json.load(source)
    snapshot: dict[str, Any] = {
        "case": case, "rules": rules, "at": target.isoformat(), "as_of": cutoff.isoformat(),
        "tables": tables, "events": tables["events"], "sampling_seconds": sampling,
        "evidence": [{"source": "observed/cases.csv", "case_id": case_id,
                      "at": target.isoformat(), "as_of": cutoff.isoformat()}],
        "limitations": ["Synthetic observations; no real network action or evaluation answers are used."],
    }
    for table, identity in (("nodes", "node_id"), ("links", "link_id"), ("services", "service_id")):
        values = {}
        for row in tables[table]:
            if row.get("valid_from") and parse_time(row["valid_from"]) > target:
                continue
            if row.get("valid_to_exclusive") and parse_time(row["valid_to_exclusive"]) <= target:
                continue
            if row[identity] in values:
                raise SatelliteDataError(f"Duplicated active {table} ID: {row[identity]}")
            values[row[identity]] = row
        snapshot[table] = values
    routes = {}
    hops: dict[str, list[dict[str, Any]]] = {}
    for hop in tables["route_hops"]:
        hops.setdefault(hop["route_id"], []).append(hop)
    for route in tables["routes"]:
        if not parse_time(route["effective_from"]) <= target < parse_time(route["effective_to_exclusive"]):
            continue
        if route.get("route_status", "active") != "active":
            continue
        identity = route["service_id"]
        if identity in routes:
            raise SatelliteDataError(f"Overlapping active route versions for {identity}")
        ordered = sorted(hops.get(route["route_id"], []), key=lambda row: row["hop_index"])
        if not ordered or [row["hop_index"] for row in ordered] != list(range(len(ordered))):
            raise SatelliteDataError(f"Invalid route hops: {route['route_id']}")
        node_ids = [row["node_id"] for row in ordered]
        link_ids = [row["outgoing_link_id"] for row in ordered[:-1]]
        for index, link_id in enumerate(link_ids):
            link = snapshot["links"].get(link_id)
            if not link or link["source_node_id"] != node_ids[index] or link["target_node_id"] != node_ids[index + 1]:
                raise SatelliteDataError(f"Broken directed route continuity: {route['route_id']}")
        service = snapshot["services"].get(identity)
        if not service or node_ids[0] != service["source_satellite_id"] or node_ids[-1] not in service["allowed_egress_ids"].split(";"):
            raise SatelliteDataError(f"Route endpoints violate service contract: {identity}")
        routes[identity] = {**route, "nodes": node_ids, "links": link_ids}
    snapshot["routes"] = routes
    for table, identity in (("traffic", "service_id"), ("node_metrics", "node_id"),
                            ("link_metrics", "link_id"), ("service_metrics", "service_id")):
        snapshot[table] = _latest(tables[table], identity)
    return snapshot
