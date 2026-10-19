"""Pure fake-gateway contract tests: no MCP subprocess/network/database writes."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re

import pytest

from app.application.satellite_routing import optimize_snapshot
from app.infrastructure.satellite_data import SatelliteDataError, load_case
from app.infrastructure.satellite_mcp_data import (
    LATEST_KEYS, TOTAL_COLUMN, _fingerprints, load_mcp_snapshot,
)


DATA_ROOT = Path(__file__).resolve().parents[2] / "data-output" / "satellite_demo_v1"


@pytest.fixture(scope="module")
def fixture_data():
    snapshot = load_case(DATA_ROOT, "CASE-001")
    fingerprints, headers = _fingerprints(DATA_ROOT)
    rows = {name: list(snapshot[name].values()) for name in ("nodes", "links", "services", *LATEST_KEYS)}
    rows["routes"] = [{key: value for key, value in row.items() if key not in ("nodes", "links")}
                      for row in snapshot["routes"].values()]
    route_ids = {row["route_id"] for row in rows["routes"]}
    rows["route_hops"] = [row for row in snapshot["tables"]["route_hops"] if row["route_id"] in route_ids]
    rows["_satellite_sources"] = list(fingerprints.values())
    headers["_satellite_sources"] = ["name", "sha256", "row_count"]
    return snapshot, fingerprints, headers, rows


class FakeGateway:
    def __init__(self, fixture_data, mutate=None):
        _, _, headers, rows = fixture_data
        self.headers, self.rows = copy.deepcopy(headers), copy.deepcopy(rows)
        self.calls = []
        self.mutate = mutate

    async def call(self, server, tool, arguments):
        assert server == "duckdb" and tool == "execute_query"
        assert set(arguments) == {"sql"}
        sql = arguments["sql"]
        assert sql.startswith("SELECT ") and "LIMIT 1000" in sql
        assert not re.search(r"\b(INSERT|UPDATE|DELETE|CREATE|COPY|ATTACH|INSTALL|LOAD)\b", sql)
        assert "evaluation" not in sql
        self.calls.append(sql)
        table = re.search(r"\bFROM\s+([a-z_]+)\b", sql, re.IGNORECASE).group(1)
        records = self.rows[table]
        columns = [*self.headers[table], TOTAL_COLUMN]
        rows = [[record.get(column) for column in columns[:-1]] + [len(records)] for record in records]
        payload = {"success": True, "columns": columns, "rows": rows, "rowCount": len(rows)}
        if self.mutate:
            replacement = self.mutate(table, payload)
            if replacement is not None:
                return replacement
        return {"result": json.dumps(payload)}


def _run_fake(coroutine):
    # All gateway methods in this module are immediate pure fakes. Drive their
    # nested coroutines synchronously so tests do not create Windows asyncio's
    # socketpair/IOCP self-pipe (which is real socket I/O in a restricted sandbox).
    try:
        coroutine.send(None)
    except StopIteration as complete:
        return complete.value
    finally:
        coroutine.close()
    raise AssertionError("Fake gateway unexpectedly requested external async I/O")


def run_load(gateway):
    return _run_fake(load_mcp_snapshot(gateway, DATA_ROOT, "CASE-001"))


def test_current_optimizer_values_come_from_mcp(fixture_data):
    gateway = FakeGateway(fixture_data)
    # A changed returned capacity, not a local file value, drives the kernel.
    row = next(row for row in gateway.rows["node_metrics"] if row["node_id"] == "SAT-21")
    row["effective_capacity_mbps"] = "1500"
    snapshot = run_load(gateway)
    assert snapshot["node_metrics"]["SAT-21"]["effective_capacity_mbps"] == 1500
    assert fixture_data[0]["node_metrics"]["SAT-21"]["effective_capacity_mbps"] == 1600
    assert optimize_snapshot(snapshot, ["SAT-20"])["status"] == "no_feasible_route"
    assert snapshot["mcp_data_source"]["fingerprints_verified"]
    assert len(gateway.calls) == 10
    assert all("ROW_NUMBER()" in sql for sql in gateway.calls[-4:])
    assert all("measurement_status = 'observed'" not in sql for sql in gateway.calls)


def test_matching_mcp_snapshot_equals_public_current_values(fixture_data):
    gateway = FakeGateway(fixture_data)
    result = run_load(gateway)
    for name in ("nodes", "links", "services", "routes", *LATEST_KEYS):
        assert result[name] == fixture_data[0][name]
    assert optimize_snapshot(result, ["SAT-20"], max_options=1)["status"] == "feasible"
    assert any(row["source"] == "mcp:duckdb/execute_query" for row in result["evidence"])


def test_stale_source_hash_fails_before_loading_current_rows(fixture_data):
    gateway = FakeGateway(fixture_data)
    gateway.rows["_satellite_sources"][0]["sha256"] = "bad"
    with pytest.raises(SatelliteDataError, match="stale"):
        run_load(gateway)
    assert len(gateway.calls) == 1


@pytest.mark.parametrize("failure", ["error", "not_json", "columns", "row_width", "row_count", "total_count", "truncated"])
def test_malformed_or_truncated_result_is_rejected(fixture_data, failure):
    def mutate(table, payload):
        if table != "nodes":
            return
        if failure == "error":
            payload["success"] = False
        elif failure == "not_json":
            return {"result": "{unfinished"}
        elif failure == "columns":
            payload["columns"][0] = "unexpected_column"
        elif failure == "row_width":
            payload["rows"][0].pop()
        elif failure == "row_count":
            payload["rowCount"] += 1
        elif failure == "total_count":
            payload["rows"][0][-1] = 1001
        elif failure == "truncated":
            payload["truncated"] = True
    with pytest.raises(SatelliteDataError):
        run_load(FakeGateway(fixture_data, mutate))


@pytest.mark.parametrize("field,value,pattern", [
    ("case_id", "CASE-002", "cross-case"),
    ("timestamp", "2026-09-15T10:17:00+08:00", "future"),
    ("available_at", "2026-09-15T10:17:00+08:00", "future"),
    ("timestamp", "2026-09-15T10:13:00+08:00", "latest-known"),
    ("measurement_status", "missing", "latest-known"),
])
def test_cross_case_future_or_wrong_latest_sample_rejected(fixture_data, field, value, pattern):
    gateway = FakeGateway(fixture_data)
    gateway.rows["traffic"][0][field] = value
    with pytest.raises(SatelliteDataError, match=pattern):
        run_load(gateway)


def test_missing_object_or_broken_route_rejected(fixture_data):
    gateway = FakeGateway(fixture_data)
    gateway.rows["node_metrics"].pop()
    with pytest.raises(SatelliteDataError, match="missing/unexpected"):
        run_load(gateway)
    gateway = FakeGateway(fixture_data)
    gateway.rows["route_hops"][1]["outgoing_link_id"] = "NO-SUCH-LINK"
    with pytest.raises(SatelliteDataError, match="continuity"):
        run_load(gateway)


def test_gateway_exception_is_not_local_fallback(fixture_data):
    class FailingGateway:
        async def call(self, *args, **kwargs):
            raise RuntimeError("server unavailable")
    with pytest.raises(SatelliteDataError, match="server unavailable"):
        run_load(FailingGateway())


def test_input_case_is_not_arbitrary_sql(fixture_data):
    gateway = FakeGateway(fixture_data)
    with pytest.raises(SatelliteDataError, match="Unknown"):
        _run_fake(load_mcp_snapshot(gateway, DATA_ROOT, "CASE-001'; DROP TABLE nodes; --"))
    assert gateway.calls == []
