from __future__ import annotations
import csv
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.satellite_workflow import create_satellite_run, execute_satellite_run
from app.domain.report_schemas import WorkflowRunRead
from app.domain.satellite_schemas import SatelliteRunCreate
from app.infrastructure.database import get_session
from app.infrastructure.orm import WorkflowRunORM, ExecutionTaskORM, ArtifactORM
from app.infrastructure.satellite_config import data_root, artifact_root, mcp_public_status

router = APIRouter(prefix="/satellite", tags=["satellite-planning"])


@router.get("/cases")
def list_cases():
    root = data_root() / "observed"
    try:
        with (root / "cases.csv").open(encoding="utf-8-sig", newline="") as f:
            cases = list(csv.DictReader(f))
        with (root / "nodes.csv").open(encoding="utf-8-sig", newline="") as f:
            nodes = list(csv.DictReader(f))
        counts = {"satellites": sum(x["node_type"] == "satellite" for x in nodes),
            "ground_stations": sum(x["node_type"] == "ground_station" for x in nodes)}
        for table in ("links", "services"):
            with (root / f"{table}.csv").open(encoding="utf-8-sig", newline="") as f:
                counts[table] = sum(1 for _ in csv.DictReader(f))
        return [{**case, **counts} for case in cases]
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=503, detail="卫星观测数据不可用，请检查配置。") from exc


@router.get("/mcp/status")
def get_mcp_status():
    try:
        return mcp_public_status()
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="MCP配置不可用") from exc


def _serialize(session, run):
    tasks = session.scalars(select(ExecutionTaskORM).where(ExecutionTaskORM.run_id == run.id).order_by(ExecutionTaskORM.order_index)).all()
    artifacts = session.scalars(select(ArtifactORM).where(ArtifactORM.run_id == run.id).order_by(ArtifactORM.created_at)).all()
    return {"id": run.id, "workflow_type": run.workflow_type, "title": run.title, "requirement": run.requirement,
        "status": run.status, "result_contract": run.result_contract, "input_files": run.input_files,
        "summary": run.summary, "error": run.error, "created_at": run.created_at, "started_at": run.started_at,
        "completed_at": run.completed_at, "updated_at": run.updated_at, "tasks": tasks,
        "artifacts": [{"id": item.id, "task_id": item.task_id, "name": item.name, "kind": item.kind,
            "mime_type": item.mime_type, "size": item.size, "metadata": item.artifact_metadata,
            "created_at": item.created_at, "download_url": f"/satellite/runs/{run.id}/artifacts/{item.id}/download"} for item in artifacts]}


@router.post("/runs", response_model=WorkflowRunRead, status_code=202)
def create_run(payload: SatelliteRunCreate, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    try:
        identity = create_satellite_run(payload)
    except (ValueError, OSError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    background_tasks.add_task(execute_satellite_run, identity)
    run = session.get(WorkflowRunORM, identity)
    return _serialize(session, run)


@router.get("/runs", response_model=list[WorkflowRunRead])
def list_runs(session: Session = Depends(get_session)):
    runs = session.scalars(select(WorkflowRunORM).where(WorkflowRunORM.workflow_type == "satellite_planning")
        .order_by(WorkflowRunORM.created_at.desc()).limit(20)).all()
    return [_serialize(session, run) for run in runs]


@router.get("/runs/{run_id}", response_model=WorkflowRunRead)
def get_run(run_id: str, session: Session = Depends(get_session)):
    run = session.get(WorkflowRunORM, run_id)
    if not run or run.workflow_type != "satellite_planning":
        raise HTTPException(status_code=404, detail="卫星执行记录不存在")
    return _serialize(session, run)


@router.get("/runs/{run_id}/artifacts/{artifact_id}/download")
def download(run_id: str, artifact_id: str, session: Session = Depends(get_session)):
    run = session.get(WorkflowRunORM, run_id)
    if not run or run.workflow_type != "satellite_planning":
        raise HTTPException(status_code=404, detail="卫星执行记录不存在")
    item = session.scalar(select(ArtifactORM).where(ArtifactORM.run_id == run_id, ArtifactORM.id == artifact_id))
    if not item:
        raise HTTPException(status_code=404, detail="产物不存在")
    target = Path(item.path).resolve()
    try:
        target.relative_to(artifact_root())
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="产物路径不合法") from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail="产物文件已不存在")
    return FileResponse(target, media_type=item.mime_type, filename=item.name)
