"""Isolated satellite integration tests.

Run this file explicitly. It never imports app.main, starts external MCP/Feishu,
uses the configured SQL/Neo4j stores, or reads evaluation answers. SQL is an
in-memory SQLite database and every generated artifact lives under tmp_path.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import satellite_routes as routes
from app.application import satellite_workflow as workflow
from app.domain.satellite_schemas import DiagnosisInput, SatelliteRunCreate
from app.infrastructure.database import Base
from app.infrastructure.orm import ArtifactORM, ExecutionTaskORM, WorkflowRunORM
from app.infrastructure import satellite_data


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = WORKSPACE_ROOT / "data-output" / "satellite_demo_v1"


@pytest.fixture(scope="module")
def snapshot():
    """A public-observation snapshot, never an evaluation/ground-truth fixture."""
    return satellite_data.load_case(DATA_ROOT, "CASE-001")


@pytest.fixture
def harness(monkeypatch, tmp_path):
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)

    @contextmanager
    def local_scope():
        with factory() as session:
            try:
                yield session
                session.commit()
            except BaseException:
                session.rollback()
                raise

    def local_dependency():
        with factory() as session:
            yield session

    output = (tmp_path / "satellite-artifacts").resolve()
    monkeypatch.setattr(workflow, "session_scope", local_scope)
    monkeypatch.setattr(workflow, "artifact_root", lambda: output)
    monkeypatch.setattr(routes, "artifact_root", lambda: output)
    monkeypatch.setattr(workflow, "data_root", lambda: DATA_ROOT)
    monkeypatch.setattr(routes, "data_root", lambda: DATA_ROOT)
    monkeypatch.setattr(workflow, "mcp_config", lambda: {"default_mode": "file", "servers": {}})
    monkeypatch.setattr(routes, "mcp_public_status", lambda: {"default_mode": "file", "servers": [], "note": "isolated test"})

    app = FastAPI()  # Deliberately no production main/lifespan/seed/listener.
    app.include_router(routes.router, prefix="/api")
    app.dependency_overrides[routes.get_session] = local_dependency
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, session_scope=local_scope, output=output, tmp_path=tmp_path)
    app.dependency_overrides.clear()
    engine.dispose()


def payload(**overrides):
    return {"case_id": "CASE-001", "avoid_objects": ["SAT-20"], **overrides}


def diagnosis_for(current_snapshot):
    row = current_snapshot["node_metrics"]["SAT-20"]
    return {
        "schema_version": "1.0", "case_id": "CASE-001",
        "analysis_start": current_snapshot["case"]["analysis_start"],
        "analysis_end": current_snapshot["case"]["analysis_end_exclusive"],
        "as_of": current_snapshot["as_of"], "source": "development_fixture",
        "causes": [{"object_id": "SAT-20", "object_type": "satellite",
                    "mechanism": "测试输入：核查容量线索，不代表已确认根因", "status": "supported",
                    "supporting_evidence_ids": ["test-observation-1"]}],
        "evidence": [{"evidence_id": "test-observation-1", "object_id": "SAT-20",
                      "timestamp": row["timestamp"], "available_at": row["available_at"],
                      "source_file": "observed/node_metrics.csv", "record_id": row["sample_id"],
                      "description": "仅引用本案例公开的可知观测"}],
    }


def completed_run(harness, request=None):
    response = harness.client.post("/api/satellite/runs", json=request or payload())
    assert response.status_code == 202, response.text
    identity = response.json()["id"]
    # TestClient awaits BackgroundTasks, but POST serializes the planning state.
    response = harness.client.get(f"/api/satellite/runs/{identity}")
    assert response.status_code == 200, response.text
    return response.json()


def test_cases_and_config_status_are_read_only(harness):
    response = harness.client.get("/api/satellite/cases")
    assert response.status_code == 200
    cases = response.json()
    assert {"CASE-001", "CASE-008"} <= {case["case_id"] for case in cases}
    case = next(case for case in cases if case["case_id"] == "CASE-001")
    assert case["dataset_kind"] == "synthetic" and case["satellites"] > 0
    assert case["initial_diagnosis_cutoff"]
    assert harness.client.get("/api/satellite/mcp/status").json()["default_mode"] == "file"
    assert harness.client.get("/api/satellite/runs").json() == []
    assert not harness.output.exists()


def test_manual_case_runs_without_fabricating_diagnosis(harness, monkeypatch):
    opened = []
    safe_file = satellite_data._safe_file

    def observed_only(root, relative):
        assert relative.startswith("observed/") or relative == "demo_rules.json"
        assert "evaluation" not in relative and "manifest" not in relative
        opened.append(relative)
        return safe_file(root, relative)

    monkeypatch.setattr(satellite_data, "_safe_file", observed_only)
    run = completed_run(harness)
    assert run["status"] == "succeeded", run["error"]
    assert run["workflow_type"] == "satellite_planning"
    assert len(run["tasks"]) == 6  # The seventh step exists only with external diagnosis.
    assert all(task["status"] == "succeeded" for task in run["tasks"])
    assert run["summary"]["progress"] == 100
    report = run["summary"]["satellite_report"]
    assert report["diagnosis_status"] == "pending"
    for section in ("causes", "watch_items", "impact"):
        assert report[section]["status"] == "pending"
        assert report[section]["items"] == []
    assert report["provenance"]["input_source"] == "manual"
    assert report["provenance"]["avoid_objects"] == ["SAT-20"]
    assert report["provenance"]["diagnosis_is_fixture"] is False
    assert report["evidence"] == []
    assert report["route_options"]["status"] == "feasible"
    assert report["route_options"]["proposals"]
    assert all(task["evidence"]["execution_mode"] == "file" for task in run["tasks"])
    assert all(task["evidence"]["mcp_calls"] == [] for task in run["tasks"])
    assert opened and "observed/node_metrics.csv" in opened


@pytest.mark.parametrize("invalid", ["wrong_object_type", "later_analysis_window"])
def test_diagnosis_matches_object_type_and_snapshot_window(harness, snapshot, invalid):
    diagnosis = diagnosis_for(snapshot)
    if invalid == "wrong_object_type":
        diagnosis["causes"][0]["object_type"] = "ground_station"
    else:
        diagnosis["analysis_start"] = "2026-09-15T10:15:00+08:00"
        diagnosis["analysis_end"] = "2026-09-15T10:16:00+08:00"
    response = harness.client.post("/api/satellite/runs", json=payload(diagnosis=diagnosis))
    assert response.status_code == 422, response.text
    assert harness.client.get("/api/satellite/runs").json() == []


def test_external_fixture_adds_seventh_step_and_downloads_match(harness, snapshot):
    run = completed_run(harness, payload(diagnosis=diagnosis_for(snapshot)))
    assert run["status"] == "succeeded", run["error"]
    assert len(run["tasks"]) == 7
    assert [task["order_index"] for task in run["tasks"]] == list(range(1, 8))
    check = next(task for task in run["tasks"] if task["task_key"] == "accept_diagnosis")
    assert check["evidence"]["verified_references"] == 1
    assert check["evidence"]["status"] == "references_verified_not_causal_confirmation"
    report = run["summary"]["satellite_report"]
    assert report["diagnosis_status"] == "provided"
    assert report["provenance"]["input_source"] == "diagnosis_json"
    assert report["provenance"]["diagnosis_is_fixture"] is True
    assert len(run["artifacts"]) == 2
    downloaded = {}
    for artifact in run["artifacts"]:
        response = harness.client.get("/api" + artifact["download_url"])
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith(artifact["mime_type"])
        assert "attachment" in response.headers["content-disposition"]
        assert hashlib.sha256(response.content).hexdigest() == artifact["metadata"]["sha256"]
        assert artifact["size"] == len(response.content)
        downloaded[artifact["name"]] = response
    assert downloaded["satellite-report.json"].json() == report
    html = downloaded["satellite-report.html"].text
    assert html.count("<section>") == 6
    assert "模拟数据" in html and "不执行切换" in html
    assert "<table>" in html and "新预留 Mbps" in html
    malicious = deepcopy(report)
    malicious["causes"]["items"][0]["mechanism"] = '<script>alert("x")</script>'
    rendered = workflow.render_report_html(malicious)
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert len(list(harness.output.rglob("satellite-report.*"))) == 2


def test_duplicate_background_delivery_preserves_completed_run(harness):
    original = completed_run(harness)
    workflow.execute_satellite_run(original["id"])
    repeated = harness.client.get(f"/api/satellite/runs/{original['id']}").json()
    assert repeated["status"] == "succeeded"
    assert repeated["error"] == ""
    assert repeated["completed_at"] == original["completed_at"]
    assert [item["id"] for item in repeated["artifacts"]] == [item["id"] for item in original["artifacts"]]
    assert repeated["created_at"].endswith("Z")
    assert all(task["started_at"].endswith("Z") for task in repeated["tasks"])


def test_original_business_runs_and_artifacts_are_not_exposed(harness):
    legacy_file = harness.tmp_path / "business-private.json"
    legacy_file.write_text('{"private_business": true}', encoding="utf-8")
    with harness.session_scope() as session:
        session.add(WorkflowRunORM(id="legacy-business", workflow_type="data_report", title="原经营报表",
                                  requirement="分析销售和回款", status="succeeded", result_contract={}, summary={}))
        session.flush()
        session.add(ArtifactORM(id="legacy-artifact", run_id="legacy-business", name=legacy_file.name,
                               kind="business_report", path=str(legacy_file), mime_type="application/json", size=legacy_file.stat().st_size))
    run = completed_run(harness)
    assert [item["id"] for item in harness.client.get("/api/satellite/runs").json()] == [run["id"]]
    assert harness.client.get("/api/satellite/runs/legacy-business").status_code == 404
    assert harness.client.get("/api/satellite/runs/legacy-business/artifacts/legacy-artifact/download").status_code == 404
    assert harness.client.get(f"/api/satellite/runs/{run['id']}/artifacts/legacy-artifact/download").status_code == 404


@pytest.mark.parametrize("changes", [
    {"case_id": "CASE-999"}, {"case_id": "../evaluation"},
    {"avoid_objects": []}, {"avoid_objects": ["SAT-DOES-NOT-EXIST"]},
    {"avoid_objects": ["../../secret"]}, {"at": "2026-09-15T10:00:00"},
    {"at": "2026-09-15T10:16:00+08:00", "as_of": "2026-09-15T10:16:00+08:00"},
    {"at": "2027-01-01T00:00:00+08:00"},
    {"service_ids": ["SERVICE-DOES-NOT-EXIST"]},
    {"command": "arbitrary-server-command"}, {"data_root": "../evaluation"},
])
def test_invalid_identifiers_times_and_empty_targets_are_422(harness, changes):
    response = harness.client.post("/api/satellite/runs", json=payload(**changes))
    assert response.status_code == 422, response.text
    assert harness.client.get("/api/satellite/runs").json() == []
    assert not harness.output.exists()


def test_skill_spec_processor_is_the_actual_dispatch_key(harness, monkeypatch):
    invoked = []
    original = workflow.PROCESSORS["satellite.snapshot"]

    async def registered_alias(context, spec):
        invoked.append(spec["processor"])
        return await original(context, spec)

    monkeypatch.setitem(workflow.PROCESSORS, "test.snapshot.alias", registered_alias)
    identity = workflow.create_satellite_run(SatelliteRunCreate(**payload()))
    with harness.session_scope() as session:
        task = session.scalar(select(ExecutionTaskORM).where(ExecutionTaskORM.run_id == identity, ExecutionTaskORM.task_key == "load_snapshot"))
        task.skill_spec = {**task.skill_spec, "processor": "test.snapshot.alias"}
    workflow.execute_satellite_run(identity)
    run = harness.client.get(f"/api/satellite/runs/{identity}").json()
    assert run["status"] == "succeeded", run["error"]
    assert invoked == ["test.snapshot.alias"]
    assert run["tasks"][0]["evidence"]["processor"] == "test.snapshot.alias"


def test_unknown_skill_processor_fails_without_executing_a_handler(harness, monkeypatch):
    invoked = []

    async def must_not_execute(context, spec):
        invoked.append(True)
        raise AssertionError("an unregistered processor must not execute this handler")

    monkeypatch.setitem(workflow.PROCESSORS, "satellite.snapshot", must_not_execute)
    identity = workflow.create_satellite_run(SatelliteRunCreate(**payload()))
    with harness.session_scope() as session:
        task = session.scalar(select(ExecutionTaskORM).where(ExecutionTaskORM.run_id == identity, ExecutionTaskORM.task_key == "load_snapshot"))
        task.skill_spec = {**task.skill_spec, "processor": "satellite.unregistered"}
    workflow.execute_satellite_run(identity)
    run = harness.client.get(f"/api/satellite/runs/{identity}").json()
    assert run["status"] == "failed"
    assert "处理器未注册" in run["error"]
    assert run["tasks"][0]["status"] == "failed"
    assert all(task["status"] == "pending" for task in run["tasks"][1:])
    assert invoked == [] and run["artifacts"] == []
    assert not harness.output.exists()


def test_mcp_failure_is_recorded_and_does_not_fall_back_to_file(harness, monkeypatch):
    reached_routing = []

    class FailingGateway:
        def __init__(self, servers):
            self.calls = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def call(self, server, tool, arguments):
            self.calls.append({"server": server, "tool": tool, "duration_ms": 0.1,
                               "status": "failed", "error": "isolated MCP failure"})
            raise RuntimeError("isolated MCP failure")

    async def must_not_route(context, spec):
        reached_routing.append(True)
        raise AssertionError("failed MCP observations must not reach routing")

    monkeypatch.setattr(workflow, "McpGateway", FailingGateway)
    monkeypatch.setattr(workflow, "mcp_config", lambda: {"default_mode": "mcp", "servers": {}})
    monkeypatch.setitem(workflow.PROCESSORS, "satellite.routing", must_not_route)
    run = completed_run(harness)
    assert run["status"] == "failed"
    assert "isolated MCP failure" in run["error"]
    task = run["tasks"][0]
    assert task["status"] == "failed"
    assert task["evidence"]["mcp_calls"][0]["status"] == "failed"
    assert task["evidence"]["mcp_calls"][0]["server"] == "duckdb"
    assert "satellite_report" not in run["summary"]
    assert run["artifacts"] == [] and reached_routing == []
    assert not harness.output.exists()


@pytest.mark.parametrize("mutation", ["cross_case", "cross_case_record", "future", "missing_reference", "missing_record", "evaluation_path"])
def test_external_diagnosis_rejects_untraceable_evidence(harness, snapshot, mutation):
    diagnosis = deepcopy(diagnosis_for(snapshot))
    if mutation == "cross_case":
        diagnosis["case_id"] = "CASE-002"
    elif mutation == "cross_case_record":
        diagnosis["evidence"][0]["record_id"] = diagnosis["evidence"][0]["record_id"].replace("CASE-001", "CASE-002")
    elif mutation == "future":
        future = satellite_data.parse_time(diagnosis["as_of"]) + timedelta(minutes=1)
        diagnosis["evidence"][0]["available_at"] = future.isoformat()
    elif mutation == "missing_reference":
        diagnosis["causes"][0]["supporting_evidence_ids"] = ["nonexistent-evidence"]
    elif mutation == "missing_record":
        diagnosis["evidence"][0]["record_id"] = "nonexistent-observation-row"
    else:
        diagnosis["evidence"][0]["source_file"] = "evaluation/ground_truth.csv"
    response = harness.client.post("/api/satellite/runs", json=payload(diagnosis=diagnosis))
    assert response.status_code == 422, response.text
    assert harness.client.get("/api/satellite/runs").json() == []
    assert not harness.output.exists()


def test_protocol_requires_timezone_unique_evidence_and_finite_limits(snapshot):
    diagnosis = diagnosis_for(snapshot)
    assert DiagnosisInput.model_validate(diagnosis).source == "development_fixture"
    for value in (float("nan"), float("inf"), -1, 0):
        with pytest.raises(ValidationError):
            SatelliteRunCreate(**payload(max_latency_ms=value))
    duplicate = deepcopy(diagnosis)
    duplicate["evidence"].append(deepcopy(duplicate["evidence"][0]))
    with pytest.raises(ValidationError, match="evidence_id不能重复"):
        DiagnosisInput.model_validate(duplicate)
    naive = deepcopy(diagnosis)
    naive["analysis_start"] = "2026-09-15T10:00:00"
    with pytest.raises(ValidationError, match="时区"):
        DiagnosisInput.model_validate(naive)
