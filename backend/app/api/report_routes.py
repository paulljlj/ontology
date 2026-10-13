from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.report_workflow import ARTIFACT_ROOT, create_workflow_run, execute_workflow_run
from app.domain.report_schemas import WorkflowRunCreate, WorkflowRunRead
from app.infrastructure.database import get_session
from app.infrastructure.orm import ArtifactORM, ExecutionTaskORM, WorkflowRunORM, new_id


router = APIRouter(prefix="/report-runs", tags=["data-report-execution"])
@router.post("", response_model=WorkflowRunRead, status_code=202)
def create_report_run(
    payload: WorkflowRunCreate,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    requirement = payload.requirement.strip()
    if len(requirement) < 8:
        raise HTTPException(status_code=422, detail="请更完整地描述数据整理目标和期望报表。")

    run_id = new_id()
    create_workflow_run(requirement, payload.title, [], run_id=run_id)
    background_tasks.add_task(execute_workflow_run, run_id)
    run = session.get(WorkflowRunORM, run_id)
    if not run:
        # create_workflow_run 使用独立事务，过期连接重新查询一次。
        session.expire_all()
        run = session.get(WorkflowRunORM, run_id)
    return _serialize_run(session, run)


@router.get("", response_model=list[WorkflowRunRead])
def list_report_runs(session: Session = Depends(get_session)):
    runs = session.scalars(
        select(WorkflowRunORM)
        .where(WorkflowRunORM.workflow_type == "data_report")
        .order_by(WorkflowRunORM.created_at.desc())
        .limit(20)
    ).all()
    return [_serialize_run(session, run) for run in runs]


@router.get("/{run_id}", response_model=WorkflowRunRead)
def get_report_run(run_id: str, session: Session = Depends(get_session)):
    run = session.get(WorkflowRunORM, run_id)
    if not run or run.workflow_type != "data_report":
        raise HTTPException(status_code=404, detail="执行记录不存在。")
    return _serialize_run(session, run)


@router.get("/{run_id}/artifacts/{artifact_id}/download")
def download_artifact(run_id: str, artifact_id: str, session: Session = Depends(get_session)):
    artifact = session.scalar(
        select(ArtifactORM).where(ArtifactORM.id == artifact_id, ArtifactORM.run_id == run_id)
    )
    if not artifact:
        raise HTTPException(status_code=404, detail="产物不存在。")
    path = Path(artifact.path).resolve()
    try:
        path.relative_to(ARTIFACT_ROOT.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="产物路径不合法。") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="产物文件已不存在。")
    return FileResponse(path, media_type=artifact.mime_type, filename=artifact.name)


def _serialize_run(session: Session, run: WorkflowRunORM) -> dict:
    tasks = session.scalars(
        select(ExecutionTaskORM)
        .where(ExecutionTaskORM.run_id == run.id)
        .order_by(ExecutionTaskORM.order_index)
    ).all()
    artifacts = session.scalars(
        select(ArtifactORM).where(ArtifactORM.run_id == run.id).order_by(ArtifactORM.created_at)
    ).all()
    return {
        "id": run.id,
        "workflow_type": run.workflow_type,
        "title": run.title,
        "requirement": run.requirement,
        "status": run.status,
        "result_contract": run.result_contract or {},
        "input_files": [
            {
                "name": item.get("name", ""),
                "size": item.get("size", 0),
                "content_type": item.get("content_type", "application/octet-stream"),
            }
            for item in (run.input_files or [])
        ],
        "summary": run.summary or {},
        "error": run.error,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "updated_at": run.updated_at,
        "tasks": tasks,
        "artifacts": [
            {
                "id": artifact.id,
                "task_id": artifact.task_id,
                "name": artifact.name,
                "kind": artifact.kind,
                "mime_type": artifact.mime_type,
                "size": artifact.size,
                "metadata": artifact.artifact_metadata or {},
                "created_at": artifact.created_at,
                "download_url": f"/report-runs/{run.id}/artifacts/{artifact.id}/download",
            }
            for artifact in artifacts
        ],
    }
