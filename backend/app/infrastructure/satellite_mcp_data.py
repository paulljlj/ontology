"""Read authoritative routing snapshots through a real DuckDB MCP gateway.

SQL is generated exclusively by fixed templates below.  File observations are
used to establish time policy, input fingerprints, and retained diagnostic
history; all current optimizer dictionaries are replaced by MCP query results.
No fallback silently substitutes local rows when MCP validation fails.
"""
from __future__ import annotations

import csv
from datetime import timedelta
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from app.infrastructure.satellite_data import (
    OBSERVATION_TABLES, SatelliteDataError, _safe_file, _typed, load_case, parse_time,
)


MAX_ROWS = 1000
TOTAL_COLUMN = "__total_count"
LATEST_KEYS = {"traffic": "service_id", "node_metrics": "node_id",
               "link_metrics": "link_id", "service_metrics": "service_id"}


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _timestamp(value: str) -> str:
    # Reparse and normalize; no caller-supplied SQL fragment can enter a query.
    return f"CAST({_literal(parse_time(value).isoformat())} AS TIMESTAMPTZ)"


def _fingerprints(root: Path) -> tuple[dict[str, dict], dict[str, list[str]]]:
    fingerprints, headers = {}, {}
    for name in OBSERVATION_TABLES:
        source = _safe_file(root, f"observed/{name}.csv")
        digest = hashlib.sha256()
        with source.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        with source.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream)
            columns = next(reader, None)
            if not columns or len(set(columns)) != len(columns) or any(not column for column in columns):
                raise SatelliteDataError(f"Invalid observation CSV columns: {name}")
            count = 0
            for row in reader:
                if len(row) != len(columns):
                    raise SatelliteDataError(f"Malformed observation CSV row: {name}")
                count += 1
        fingerprints[name] = {"name": name, "sha256": digest.hexdigest(), "row_count": count}
        headers[name] = columns
    return fingerprints, headers


def _decode_response(raw: Any) -> dict:
    value = raw
    for _ in range(4):
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (ValueError, TypeError) as exc:
                raise SatelliteDataError("MCP query returned non-JSON or truncated JSON") from exc
        elif isinstance(value, dict) and "result" in value and "success" not in value:
            value = value["result"]
        else:
            break
    if not isinstance(value, dict) or value.get("success") is not True:
        raise SatelliteDataError("MCP query failed or returned an unsupported response")
    if value.get("truncated") or value.get("isTruncated") or value.get("hasMore"):
        raise SatelliteDataError("MCP query result is truncated")
    return value


async def _query(gateway: Any, table: str, sql: str, expected_columns: list[str]) -> list[dict[str, Any]]:
    try:
        raw = await gateway.call("duckdb", "execute_query", {"sql": sql})
    except Exception as exc:
        raise SatelliteDataError(f"MCP read-only query failed for {table}: {exc}") from exc
    payload = _decode_response(raw)
    columns, rows = payload.get("columns"), payload.get("rows")
    if not isinstance(columns, list) or not all(isinstance(column, str) for column in columns):
        raise SatelliteDataError(f"MCP returned invalid columns for {table}")
    if len(set(columns)) != len(columns) or set(columns) != set(expected_columns) | {TOTAL_COLUMN}:
        raise SatelliteDataError(f"MCP schema mismatch for {table}")
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise SatelliteDataError(f"MCP row limit exceeded or invalid rows for {table}")
    count = payload.get("rowCount")
    if isinstance(count, bool) or not isinstance(count, int) or count != len(rows):
        raise SatelliteDataError(f"MCP rowCount mismatch for {table}")
    result = []
    for row in rows:
        if not isinstance(row, list) or len(row) != len(columns):
            raise SatelliteDataError(f"MCP row width mismatch for {table}")
        record = dict(zip(columns, row))
        total = record.pop(TOTAL_COLUMN)
        if isinstance(total, bool) or not isinstance(total, (int, float)) or not math.isfinite(total) or int(total) != total or total != len(rows):
            raise SatelliteDataError(f"MCP truncated/inconsistent total count for {table}")
        if any(value is not None and not isinstance(value, (str, int, float, bool)) for value in record.values()):
            raise SatelliteDataError(f"MCP returned nested cell data for {table}")
        result.append(record)
    return result


def _typed_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_typed({key: "" if value is None else str(value) for key, value in row.items()}) for row in rows]


def _indexed(rows: list[dict[str, Any]], key: str, table: str) -> dict[str, dict]:
    result = {}
    for row in rows:
        identity = row.get(key)
        if not identity or identity in result:
            raise SatelliteDataError(f"MCP duplicate/empty {key} in {table}")
        result[identity] = row
    return result


def _same_ids(actual: dict, expected: dict, table: str) -> None:
    if set(actual) != set(expected):
        raise SatelliteDataError(f"MCP missing/unexpected current objects in {table}; stale or incomplete database")


async def load_mcp_snapshot(gateway: Any, data_root: Path, case_id: str, *,
                            at: str | None = None, as_of: str | None = None) -> dict[str, Any]:
    """Return load_case-compatible numeric dictionaries whose source is MCP.

    Raises SatelliteDataError on transport, fingerprint, schema, completeness,
    case, temporal, or route-integrity failure. Does not start MCP processes or
    write a database: the caller owns an already configured async gateway.
    """
    root = Path(data_root).resolve()
    snapshot = load_case(root, case_id, at=at, as_of=as_of)
    fingerprints, headers = _fingerprints(root)
    source_sql = f"SELECT *, COUNT(*) OVER () AS {TOTAL_COLUMN} FROM _satellite_sources ORDER BY name LIMIT {MAX_ROWS}"
    source_rows = await _query(gateway, "_satellite_sources", source_sql, ["name", "sha256", "row_count"])
    imported = _indexed(source_rows, "name", "_satellite_sources")
    if set(imported) != set(OBSERVATION_TABLES):
        raise SatelliteDataError("MCP source catalogue does not match the observation allowlist")
    for name, expected in fingerprints.items():
        actual = imported[name]
        if (actual.get("sha256") != expected["sha256"] or isinstance(actual.get("row_count"), bool)
                or str(actual.get("row_count")) != str(expected["row_count"])):
            raise SatelliteDataError(f"MCP database is stale: source hash/row count mismatch for {name}; prepare it again")

    instant, cutoff = _timestamp(snapshot["at"]), _timestamp(snapshot["as_of"])
    target_dt, cutoff_dt = parse_time(snapshot["at"]), parse_time(snapshot["as_of"])
    sampling = float(snapshot["sampling_seconds"])
    case_literal = _literal(case_id)
    queried: dict[str, list[dict[str, Any]]] = {}
    for table in ("nodes", "links", "services"):
        where = (f" WHERE CAST(valid_from AS TIMESTAMPTZ) <= {instant} "
                 f"AND CAST(valid_to_exclusive AS TIMESTAMPTZ) > {instant}") if table == "nodes" else ""
        sql = f"SELECT *, COUNT(*) OVER () AS {TOTAL_COLUMN} FROM {table}{where} LIMIT {MAX_ROWS}"
        rows = _typed_rows(await _query(gateway, table, sql, headers[table]))
        if any(row.get("case_id", case_id) != case_id for row in rows):
            raise SatelliteDataError(f"MCP returned cross-case static rows for {table}")
        queried[table] = rows

    route_filter = (f"r.case_id = {case_literal} AND CAST(r.available_at AS TIMESTAMPTZ) <= {cutoff} "
                    f"AND CAST(r.effective_from AS TIMESTAMPTZ) <= {instant} "
                    f"AND CAST(r.effective_to_exclusive AS TIMESTAMPTZ) > {instant} AND r.route_status = 'active'")
    route_sql = f"SELECT r.*, COUNT(*) OVER () AS {TOTAL_COLUMN} FROM routes r WHERE {route_filter} LIMIT {MAX_ROWS}"
    queried["routes"] = _typed_rows(await _query(gateway, "routes", route_sql, headers["routes"]))
    hop_sql = (f"SELECT h.*, COUNT(*) OVER () AS {TOTAL_COLUMN} FROM route_hops h JOIN routes r "
               f"ON h.case_id = r.case_id AND h.route_id = r.route_id WHERE {route_filter} LIMIT {MAX_ROWS}")
    queried["route_hops"] = _typed_rows(await _query(gateway, "route_hops", hop_sql, headers["route_hops"]))
    for table, key in LATEST_KEYS.items():
        sql = (f"SELECT * EXCLUDE (__rn), COUNT(*) OVER () AS {TOTAL_COLUMN} FROM ("
               f"SELECT *, ROW_NUMBER() OVER (PARTITION BY {key} ORDER BY CAST(timestamp AS TIMESTAMPTZ) DESC, "
               f"CAST(available_at AS TIMESTAMPTZ) DESC) AS __rn FROM {table} "
               f"WHERE case_id = {case_literal} AND CAST(timestamp AS TIMESTAMPTZ) <= {instant} "
               f"AND CAST(timestamp AS TIMESTAMPTZ) + INTERVAL '{sampling:g} seconds' <= {cutoff} "
               f"AND CAST(available_at AS TIMESTAMPTZ) <= {cutoff}) visible "
               f"WHERE __rn = 1 ORDER BY {key} LIMIT {MAX_ROWS}")
        queried[table] = _typed_rows(await _query(gateway, table, sql, headers[table]))

    # Validate the result independently of SQL filtering; do not trust a fake,
    # misconfigured, or future implementation to have respected the predicate.
    for table in ("routes", "route_hops", *LATEST_KEYS):
        for row in queried[table]:
            if row.get("case_id") != case_id:
                raise SatelliteDataError(f"MCP returned cross-case observations in {table}")
            if row.get("available_at") and parse_time(row["available_at"]) > cutoff_dt:
                raise SatelliteDataError(f"MCP returned future available_at in {table}")
            if row.get("timestamp") and (parse_time(row["timestamp"]) > target_dt
                    or parse_time(row["timestamp"]) + timedelta(seconds=sampling) > cutoff_dt):
                raise SatelliteDataError(f"MCP returned future/incomplete sample in {table}")
    for row in queried["nodes"]:
        if not parse_time(row["valid_from"]) <= target_dt < parse_time(row["valid_to_exclusive"]):
            raise SatelliteDataError("MCP returned an inactive/future node")

    replacement: dict[str, Any] = {}
    for table, key in (("nodes", "node_id"), ("links", "link_id"), ("services", "service_id"), *LATEST_KEYS.items()):
        replacement[table] = _indexed(queried[table], key, table)
        _same_ids(replacement[table], snapshot[table], table)
    hops_by_route: dict[str, list[dict]] = {}
    for row in queried["route_hops"]:
        hops_by_route.setdefault(row["route_id"], []).append(row)
    routes = {}
    for route in queried["routes"]:
        if (route.get("route_status") != "active" or not
                parse_time(route["effective_from"]) <= target_dt < parse_time(route["effective_to_exclusive"])):
            raise SatelliteDataError("MCP returned an inactive/future route")
        identity = route["service_id"]
        if identity in routes:
            raise SatelliteDataError("MCP returned overlapping current route versions")
        hops = sorted(hops_by_route.pop(route["route_id"], []), key=lambda row: row["hop_index"])
        if len(hops) < 2 or [row["hop_index"] for row in hops] != list(range(len(hops))):
            raise SatelliteDataError("MCP returned incomplete/duplicate route hops")
        node_ids = [row["node_id"] for row in hops]
        link_ids = [row["outgoing_link_id"] for row in hops[:-1]]
        if any(node not in replacement["nodes"] for node in node_ids):
            raise SatelliteDataError("MCP route references an unknown node")
        for index, identity_link in enumerate(link_ids):
            link = replacement["links"].get(identity_link)
            if not link or (link["source_node_id"], link["target_node_id"]) != (node_ids[index], node_ids[index + 1]):
                raise SatelliteDataError("MCP route has broken directed link continuity")
        service = replacement["services"].get(identity)
        if (not service or node_ids[0] != service["source_satellite_id"]
                or node_ids[-1] not in service["allowed_egress_ids"].split(";")):
            raise SatelliteDataError("MCP route violates source/allowed-egress contract")
        routes[identity] = {**route, "nodes": node_ids, "links": link_ids}
    if hops_by_route:
        raise SatelliteDataError("MCP returned unrelated route hops")
    _same_ids(routes, snapshot["routes"], "routes")
    replacement["routes"] = routes
    # Require exactly the latest known sample, including missing measurements;
    # an older good row may not replace a newest missing one.
    for table in LATEST_KEYS:
        for identity, row in replacement[table].items():
            expected = snapshot[table][identity]
            if (parse_time(row["timestamp"]) != parse_time(expected["timestamp"])
                    or parse_time(row["available_at"]) != parse_time(expected["available_at"])
                    or row.get("measurement_status") != expected.get("measurement_status")):
                raise SatelliteDataError(f"MCP did not preserve latest-known measurement in {table}")
    snapshot.update(replacement)
    snapshot["mcp_data_source"] = {
        "server": "duckdb", "tool": "execute_query", "source": "MCP query result rows",
        "queried_tables": ["_satellite_sources", *queried], "read_only": True,
        "fingerprints_verified": True, "row_counts": {table: len(rows) for table, rows in queried.items()},
        "optimizer_keys_from_mcp": ["nodes", "links", "services", "routes", *LATEST_KEYS],
    }
    for table, rows in queried.items():
        snapshot["evidence"].append({"source": "mcp:duckdb/execute_query", "observation_table": table,
                                     "case_id": case_id, "at": snapshot["at"], "as_of": snapshot["as_of"],
                                     "returned_rows": len(rows), "source_sha256": fingerprints[table]["sha256"]})
    snapshot["limitations"].append("Routing current rows came from MCP; retained diagnostic history/rules came from allowlisted files.")
    return snapshot
