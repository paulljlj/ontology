from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.report_workflow import ARTIFACT_ROOT, create_workflow_run, execute_workflow_run
from app.domain.report_schemas import WorkflowRunRead
from app.infrastructure.database import get_session
from app.infrastructure.orm import ArtifactORM, ExecutionTaskORM, WorkflowRunORM, new_id


router = APIRouter(prefix="/report-runs", tags=["data-report-execution"])
MAX_FILE_SIZE = 25 * 1024 * 1024
SUPPORTED_SUFFIXES = {".csv", ".xlsx"}


@router.post("", response_model=WorkflowRunRead, status_code=202)
async def create_report_run(
    background_tasks: BackgroundTasks,
    requirement: str = Form(...),
    title: str = Form("数据整理与报表生成"),
    files: list[UploadFile] = File(...),
    session: Session = Depends(get_session),
):
    if len(requirement.strip()) < 8:
        raise HTTPException(status_code=422, detail="请更完整地描述数据整理目标和期望报表。")
    if not files:
        raise HTTPException(status_code=422, detail="请至少上传一个 CSV 或 XLSX 文件。")

    run_id = new_id()
    input_directory = ARTIFACT_ROOT / run_id / "inputs"
    input_directory.mkdir(parents=True, exist_ok=True)
    stored_files: list[dict] = []
    used_names: set[str] = set()
    for upload in files:
        original_name = Path(upload.filename or "data").name
        suffix = Path(original_name).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise HTTPException(status_code=415, detail=f"不支持 {original_name}；首版支持 CSV 和 XLSX。")
        safe_name = _unique_name(original_name, used_names)
        destination = input_directory / safe_name
        size = 0
        with destination.open("wb") as handle:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_FILE_SIZE:
                    destination.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail=f"{original_name} 超过 25 MB 限制。")
                handle.write(chunk)
        stored_files.append(
            {
                "name": original_name,
                "stored_name": safe_name,
                "path": str(destination.resolve()),
                "size": size,
                "content_type": upload.content_type or "application/octet-stream",
            }
        )

    create_workflow_run(requirement, title, stored_files, run_id=run_id)
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


def _unique_name(name: str, used: set[str]) -> str:
    path = Path(name)
    candidate = path.name
    index = 2
    while candidate.lower() in used:
        candidate = f"{path.stem}_{index}{path.suffix}"
        index += 1
    used.add(candidate.lower())
    return candidate
