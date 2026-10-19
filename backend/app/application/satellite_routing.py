"""Bounded, joint rerouting of observed service demands; never a root-cause oracle."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
import math
from pathlib import Path
from typing import Any

from app.infrastructure.satellite_data import SatelliteDataError, load_case, parse_time


PATHS_PER_SERVICE = 12
MAX_HOPS = 6
MAX_PATH_EXPANSIONS = 4000
MAX_ASSIGNMENTS = 20000


def _resources(route: dict[str, Any]) -> list[str]:
    return list(route["nodes"]) + list(route["links"])


def optimize_routes(data_root: Path, case_id: str, avoid_objects: list[str], *, at: str | None = None,
                    as_of: str | None = None, service_ids: list[str] | None = None,
                    max_utilization_pct: float = 85, max_latency_ms: float = 150,
                    max_options: int = 3) -> dict[str, Any]:
    """Read the observation-only snapshot, then delegate to the routing kernel."""
    try:
        data = load_case(data_root, case_id, at=at, as_of=as_of)
    except (SatelliteDataError, OSError, KeyError) as exc:
        return {"status": "insufficient_data", "case_id": case_id, "at": at, "as_of": as_of,
                "avoid_objects": sorted(set(avoid_objects)), "proposals": [], "evidence": [],
                "unresolved_risks": [], "limitations": ["No baseline/future filling or evaluation inputs."],
                "reason": str(exc)}
    return optimize_snapshot(data, avoid_objects, service_ids=service_ids,
                             max_utilization_pct=max_utilization_pct, max_latency_ms=max_latency_ms,
                             max_options=max_options)


def optimize_snapshot(snapshot: dict[str, Any], avoid_objects: list[str], *,
                      service_ids: list[str] | None = None, max_utilization_pct: float = 85,
                      max_latency_ms: float = 150, max_options: int = 3) -> dict[str, Any]:
    """Plan all selected flows together using offered-demand capacity reservations.

    avoid_objects are an explicit caller decision, not an inferred diagnosis.
    Every result is a point-in-time model estimate, never a real switch or an
    estimate of restored availability. Existing unrelated bottlenecks may remain
    only when not worsened. Missing latest telemetry is not replaced by history.
    """
    data = snapshot
    case_id, at, as_of = data["case"]["case_id"], data["at"], data["as_of"]
    if not 0 < max_utilization_pct <= 100 or not math.isfinite(max_latency_ms) or max_latency_ms <= 0:
        raise ValueError("Invalid utilization or latency constraint")
    if not 1 <= max_options <= 10:
        raise ValueError("max_options must be between 1 and 10")
    result: dict[str, Any] = {
        "status": "insufficient_data", "case_id": case_id, "at": at, "as_of": as_of,
        "avoid_objects": sorted(set(avoid_objects)), "proposals": [], "evidence": [], "unresolved_risks": [],
        "limitations": [
            "Avoided objects are supplied by the caller; this function does not diagnose causes.",
            "Bounded candidate-path/backtracking search, not a global optimality proof.",
            "Point-in-time conservative offered-demand reservations; not observed post-switch forwarding.",
            "Latency uses propagation + 1.5ms/node + a simple load queue model, not an SLA guarantee.",
            "Capacity/latency feasibility does not establish service availability SLA compliance.",
            "No predicted availability, calibrated failure probability, real switch, or future telemetry.",
        ],
        "search_limits": {"paths_per_service": PATHS_PER_SERVICE, "max_hops": MAX_HOPS,
                          "path_expansions": MAX_PATH_EXPANSIONS, "assignments": MAX_ASSIGNMENTS},
    }
    result.update(evidence=list(data.get("evidence", [])))
    target = parse_time(data["at"])
    cutoff = parse_time(data["as_of"])
    sampling = data["sampling_seconds"]
    if sampling <= 0 or target + timedelta(seconds=sampling) > cutoff:
        result["reason"] = "Requested snapshot interval is not complete at as_of"
        return result
    nodes, links, services, routes = (data[key] for key in ("nodes", "links", "services", "routes"))
    # Snapshots may originate from MCP rather than load_case. Validate referential
    # integrity here too, before looking up capacities or constructing paths.
    for identity, route in routes.items():
        route_nodes, route_links = route.get("nodes", []), route.get("links", [])
        if (identity not in services or len(route_nodes) < 2 or len(route_links) != len(route_nodes) - 1
                or len(set(route_nodes)) != len(route_nodes) or any(node not in nodes for node in route_nodes)
                or any(edge not in links for edge in route_links)):
            result["reason"] = "Current route references missing/invalid nodes, links, or service"
            return result
        if any((links[edge].get("source_node_id"), links[edge].get("target_node_id")) !=
               (route_nodes[index], route_nodes[index + 1]) for index, edge in enumerate(route_links)):
            result["reason"] = "Current route has broken directed continuity"
            return result
        if (route_nodes[0] != services[identity]["source_satellite_id"]
                or route_nodes[-1] not in services[identity]["allowed_egress_ids"].split(";")):
            result["reason"] = "Current route violates service endpoints"
            return result
    avoid = set(avoid_objects)
    unknown = avoid - set(nodes) - set(links)
    if unknown:
        result["reason"] = f"Unknown avoided objects: {', '.join(sorted(unknown))}"
        return result
    if service_ids is None:
        selected = [identity for identity, route in routes.items() if avoid.intersection(_resources(route))]
    else:
        selected = list(dict.fromkeys(service_ids))
        if set(selected) - set(services):
            result["reason"] = "Requested service_ids contain unknown services"
            return result
    result["selected_service_ids"] = selected
    if not selected:
        result.update(status="no_change_needed", reason="No active service route intersects the requested avoided objects")
        return result
    if set(services) - set(routes):
        result["reason"] = "Current routes are missing for some services; joint capacity cannot be checked"
        return result

    def current(row: dict[str, Any] | None) -> bool:
        return bool(row and row.get("measurement_status") == "observed"
                    and row.get("case_id", case_id) == case_id
                    and parse_time(row["available_at"]) <= cutoff
                    and parse_time(row["timestamp"]) + timedelta(seconds=sampling) <= cutoff
                    and 0 <= (target - parse_time(row["timestamp"])).total_seconds() < sampling)

    demands: dict[str, float] = {}
    for identity in services:
        row = data["traffic"].get(identity)
        if not current(row) or row.get("offered_mbps") is None or not math.isfinite(row["offered_mbps"]) or row["offered_mbps"] < 0:
            result["reason"] = f"Current offered demand is missing/stale for {identity}; no baseline or future fill allowed"
            return result
        demands[identity] = row["offered_mbps"]
        result["evidence"].append({"source": "observed/traffic.csv", "service_id": identity,
                                   "timestamp": row["timestamp"], "available_at": row["available_at"],
                                   "offered_mbps": row["offered_mbps"]})

    capacities: dict[str, float] = {}
    telemetry: dict[str, dict[str, Any]] = {}
    missing: set[str] = set()
    unusable: dict[str, str] = {}
    all_objects = {**nodes, **links}
    for identity in all_objects:
        is_node = identity in nodes
        row = data["node_metrics" if is_node else "link_metrics"].get(identity)
        sent_field = "forwarded_mbps" if is_node else "transmitted_mbps"
        if (not current(row) or any(row.get(field) is None or not math.isfinite(row[field]) or row[field] < 0
                                   for field in ("effective_capacity_mbps", "ingress_mbps", sent_field))):
            missing.add(identity)
            continue
        if (row[sent_field] > row["ingress_mbps"] + .001
                or row[sent_field] > row["effective_capacity_mbps"] + .001):
            missing.add(identity)
            continue
        cap = row["effective_capacity_mbps"]
        capacities[identity] = cap
        telemetry[identity] = row
        if cap <= 0 or (not is_node and row.get("operational_state") != "UP"):
            unusable[identity] = "resource_down_or_zero_capacity"
            continue
        if is_node:
            node = nodes[identity]
            if not node.get("valid_from") or not node.get("valid_to_exclusive"):
                missing.add(identity)
                continue
            if not (parse_time(node["valid_from"]) <= target
                    and parse_time(node["valid_to_exclusive"]) >= target + timedelta(seconds=sampling)):
                unusable[identity] = "outside_node_validity_window"
                continue
        else:
            link = links[identity]
            propagation = link.get("propagation_latency_ms")
            if propagation is None or not math.isfinite(propagation) or propagation < 0:
                missing.add(identity)
                continue
            if link.get("source_node_id") not in nodes or link.get("target_node_id") not in nodes:
                missing.add(identity)
                continue
            if link.get("direction", "directed") != "directed":
                unusable[identity] = "unsupported_direction"
                continue
            if not (parse_time(link["visible_from"]) <= target
                    and parse_time(link["visible_to_exclusive"]) >= target + timedelta(seconds=sampling)):
                unusable[identity] = "outside_contact_window"
                continue
        received = row.get("ingress_mbps")
        sent = row.get("forwarded_mbps" if is_node else "transmitted_mbps")
        # Separate capacity saturation from additional observed equipment/transport losses.
        if received is not None and sent is not None and min(received, cap) > 0:
            extra_loss = 1 - sent / min(received, cap)
            if extra_loss > 0.02:
                unusable[identity] = "observed_non_capacity_loss_gt_2pct"

    baseline: defaultdict[str, float] = defaultdict(float)
    for identity, route in routes.items():
        for resource in _resources(route):
            baseline[resource] += demands[identity]
    unknown_used = set(baseline) & missing
    if unknown_used:
        result["reason"] = "Current-route telemetry is missing/stale/invalid: " + ", ".join(sorted(unknown_used))
        return result
    # At a downstream resource offered demand is not actual arrival. Bound each
    # known flow's arrival from below by subtracting ALL observed upstream losses
    # (even losses possibly belonging to other traffic). The remainder of observed
    # ingress is therefore a conservative UPPER bound on unmodelled background.
    # This may over-reserve capacity, but cannot subtract away hidden background
    # just because a known flow lost packets before reaching this resource.
    arrival_lower: defaultdict[str, float] = defaultdict(float)
    for identity, route in routes.items():
        lower = demands[identity]
        ordered_resources = []
        for index, node in enumerate(route["nodes"]):
            ordered_resources.append(node)
            if index < len(route["links"]):
                ordered_resources.append(route["links"][index])
        for resource in ordered_resources:
            row = telemetry[resource]
            arrival_lower[resource] += lower
            sent = row.get("forwarded_mbps", row.get("transmitted_mbps"))
            lower = max(0, lower - max(0, row["ingress_mbps"] - sent))
    if any(arrival_lower[resource] > telemetry[resource]["ingress_mbps"] + .01 for resource in baseline):
        result["reason"] = "Observed resource arrivals conflict with offered demands/upstream flow conservation"
        return result
    background = {resource: max(0, telemetry[resource]["ingress_mbps"] - arrival_lower[resource])
                  for resource in baseline}
    for resource, amount in background.items():
        baseline[resource] += amount
    # A currently unused alternative can still carry other observed traffic.
    for resource, row in telemetry.items():
        if resource not in baseline and row.get("ingress_mbps", 0) > 0:
            background[resource] = row["ingress_mbps"]
            baseline[resource] = row["ingress_mbps"]
    result["limitations"].append("Background reservations use conservative arrival lower bounds after upstream losses; they may overestimate background, never assume offered=arrived.")
    limit = max_utilization_pct / 100

    def risk_rows(loads: dict[str, float]) -> list[dict[str, Any]]:
        risks = []
        for resource, load in loads.items():
            capacity = capacities.get(resource)
            if load <= 0:
                continue
            if capacity is None or capacity <= 0 or load > capacity * limit + 1e-7 or resource in unusable:
                risks.append({"object_id": resource, "reserved_demand_mbps": round(load, 4),
                              "capacity_mbps": capacity,
                              "estimated_demand_utilization_pct": round(load / capacity * 100, 4) if capacity else None,
                              "reason": unusable.get(resource, "existing_capacity_headroom_violation")})
        return risks

    result["unresolved_risks"] = risk_rows(baseline)
    result["limitations"].append("Observed additional non-capacity loss above 2% excludes a candidate resource (demo safety policy).")
    adjacency: defaultdict[str, list[tuple[str, str]]] = defaultdict(list)
    for identity, link in links.items():
        adjacency[link["source_node_id"]].append((link["target_node_id"], identity))
    for outgoing in adjacency.values():
        outgoing.sort(key=lambda item: (links[item[1]].get("propagation_latency_ms") or 0, item[1]))
    candidates: dict[str, list[dict[str, Any]]] = {}
    path_expansions = 0
    path_truncated = False
    missing_candidates: set[str] = set()
    for identity in selected:
        service = services[identity]
        start = service["source_satellite_id"]
        exits = set(service["allowed_egress_ids"].split(";"))
        if start in avoid or exits.issubset(avoid):
            result.update(status="no_feasible_route", reason=f"Fixed source/allowed destination for {identity} is avoided; changing relay cannot bypass it")
            return result
        found = []
        expansions = 0

        def walk(node: str, node_path: list[str], link_path: list[str]):
            nonlocal expansions, path_expansions, path_truncated
            if expansions >= MAX_PATH_EXPANSIONS or len(found) >= PATHS_PER_SERVICE:
                path_truncated = True
                return
            expansions += 1
            path_expansions += 1
            if node in avoid or node in unusable:
                return
            if node in missing:
                missing_candidates.add(node)
                return
            if node in exits:
                found.append({"nodes": list(node_path), "links": list(link_path)})
                return
            if len(link_path) >= MAX_HOPS:
                return
            for next_node, edge in adjacency.get(node, []):
                if next_node in node_path or edge in avoid or edge in unusable:
                    continue
                if edge in missing:
                    missing_candidates.add(edge)
                    continue
                walk(next_node, node_path + [next_node], link_path + [edge])

        walk(start, [start], [])
        if not found:
            result.update(status="insufficient_data" if missing_candidates else "no_feasible_route",
                          reason=f"No usable directed alternative found for {identity} within the search bounds",
                          missing_candidate_objects=sorted(missing_candidates), blocked_objects=unusable)
            return result
        candidates[identity] = found

    residual: defaultdict[str, float] = defaultdict(float, baseline)
    for identity in selected:
        for resource in _resources(routes[identity]):
            residual[resource] -= demands[identity]
    ordered = sorted(selected, key=lambda identity: (len(candidates[identity]), -demands[identity], identity))
    assignments = 0
    truncated = False
    proposals: list[dict[str, Any]] = []

    def latency(route: dict[str, Any], loads: dict[str, float]) -> float:
        total = sum(float(links[edge]["propagation_latency_ms"]) for edge in route["links"])
        total += 1.5 * len(route["nodes"])
        for resource in _resources(route):
            cap = capacities.get(resource, 0)
            utilization = loads.get(resource, 0) / cap if cap else 3
            total += max(0, min(utilization, 3) - .75) * 25
        return total

    baseline_latencies = {identity: latency(route, baseline) for identity, route in routes.items()}

    def finish(choices: dict[str, dict[str, Any]], loads: dict[str, float]):
        affected = {resource for route in choices.values() for resource in _resources(route)}
        # Include all unmoved flows sharing a changed node/link in latency checks.
        assessments = []
        for identity, original in routes.items():
            route = choices.get(identity, original)
            estimated = latency(route, loads)
            shared = bool(affected.intersection(_resources(route)))
            bound = min(max_latency_ms, float(services[identity].get("sla_latency_ms") or max_latency_ms))
            if identity in choices or shared:
                if estimated > bound + 1e-7:
                    return
            elif estimated > bound and estimated > baseline_latencies[identity] + 1e-7:
                return
            assessments.append({"service_id": identity, "changed": identity in choices and
                                (route["nodes"] != original["nodes"] or route["links"] != original["links"]),
                                "shares_changed_resource": shared, "estimated_latency_ms": round(estimated, 4),
                                "latency_limit_ms": bound, "estimated_latency_within_limit": estimated <= bound,
                                "availability_sla_evaluated": False})
        changes = [{"service_id": identity, "before_nodes": routes[identity]["nodes"],
                    "before_links": routes[identity]["links"], "after_nodes": choices[identity]["nodes"],
                    "after_links": choices[identity]["links"], "offered_mbps": demands[identity],
                    "estimated_latency_ms": next(row["estimated_latency_ms"] for row in assessments if row["service_id"] == identity),
                    "estimate_kind": "model_estimate_not_measured"} for identity in selected
                   if choices[identity]["nodes"] != routes[identity]["nodes"] or choices[identity]["links"] != routes[identity]["links"]]
        if not changes:
            return
        resources = [{"object_id": resource, "before_reserved_demand_mbps": round(baseline.get(resource, 0), 4),
                      "after_reserved_demand_mbps": round(loads.get(resource, 0), 4), "capacity_mbps": capacities[resource],
                      "estimated_demand_utilization_pct": round(loads.get(resource, 0) / capacities[resource] * 100, 4),
                      "reserved_background_mbps": round(background.get(resource, 0), 4),
                      "observed_ingress_mbps": telemetry[resource].get("ingress_mbps"),
                      "observed_forwarded_mbps": telemetry[resource].get("forwarded_mbps", telemetry[resource].get("transmitted_mbps"))}
                     for resource in sorted(affected)]
        risks = risk_rows(loads)
        # Existing unrelated problems can persist, but may never gain load.
        if any(row["object_id"] in affected or loads[row["object_id"]] > baseline.get(row["object_id"], 0) + 1e-7 for row in risks):
            return
        proposals.append({"proposal_id": f"option-{len(proposals) + 1}", "changes": changes,
                          "resources": resources, "service_assessments": assessments, "unresolved_risks": risks,
                          "estimated_total_changed_latency_ms": round(sum(item["estimated_latency_ms"] for item in changes), 4),
                          "availability_claim": "not_estimated_requires_post_change_observation",
                          "action": "simulation_only_no_network_switch"})

    def assign(index: int, choices: dict[str, dict[str, Any]]):
        nonlocal assignments, truncated
        if len(proposals) >= max_options:
            return
        if assignments >= MAX_ASSIGNMENTS:
            truncated = True
            return
        if index == len(ordered):
            finish(choices, residual)
            return
        identity = ordered[index]
        for route in candidates[identity]:
            if assignments >= MAX_ASSIGNMENTS:
                truncated = True
                break
            assignments += 1
            resources = _resources(route)
            if any(residual[resource] + demands[identity] > capacities[resource] * limit + 1e-7 for resource in resources):
                continue
            for resource in resources:
                residual[resource] += demands[identity]
            choices[identity] = route
            assign(index + 1, choices)
            choices.pop(identity)
            for resource in resources:
                residual[resource] -= demands[identity]
            if len(proposals) >= max_options or assignments >= MAX_ASSIGNMENTS:
                if assignments >= MAX_ASSIGNMENTS:
                    truncated = True
                break

    assign(0, {})
    proposals.sort(key=lambda item: item["estimated_total_changed_latency_ms"])
    result.update(status="feasible" if proposals else "no_feasible_route", proposals=proposals,
                  search={"candidate_paths": {identity: len(paths) for identity, paths in candidates.items()},
                          "path_expansions": path_expansions, "assignments": assignments,
                          "truncated": truncated or path_truncated},
                  reason="Feasible joint reroute estimates found" if proposals else "No assignment satisfies joint capacity/headroom and latency constraints within the bounded search")
    if proposals:
        result["unresolved_risks"] = proposals[0]["unresolved_risks"]
        used = {resource["object_id"] for proposal in proposals for resource in proposal["resources"]}
        used.update(row["object_id"] for row in result["unresolved_risks"])
        used.update(avoid.intersection(telemetry))
        for identity in sorted(used):
            row = telemetry[identity]
            result["evidence"].append({"source": "observed/node_metrics.csv" if identity in nodes else "observed/link_metrics.csv",
                                       "object_id": identity, "sample_id": row.get("sample_id"),
                                       "timestamp": row["timestamp"], "available_at": row["available_at"],
                                       "effective_capacity_mbps": row["effective_capacity_mbps"]})
    return result
