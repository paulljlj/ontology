from datetime import UTC, datetime
from random import randint
from time import perf_counter

from sqlalchemy.orm import Session

from app.application.ontology_service import (
    create_instance_by_class_name,
    get_instance_or_404,
    log_execution,
    read_instance,
    relate,
)
from app.domain.constants import ClassName, RelationType


def trigger_mock_jenkins(
    session: Session,
    job_id: str | None,
    feature_id: str | None,
    environment: str,
) -> dict:
    start = perf_counter()
    target = get_instance_or_404(session, job_id or feature_id) if (job_id or feature_id) else None
    build_number = randint(100, 999)
    job = (
        target
        if target and target.ontology_class.name == ClassName.JENKINS_JOB
        else create_instance_by_class_name(
            session,
            ClassName.JENKINS_JOB,
            "ontology-core-service",
            "success",
            {"environment": environment, "build_number": build_number},
        )
    )
    job.properties = {
        **(job.properties or {}),
        "environment": environment,
        "build_number": build_number,
        "triggered_at": datetime.now(UTC).isoformat(),
        "mock": True,
    }
    job.status = "success"

    if target and target.id != job.id:
        relate(session, target.id, job.id, RelationType.TRIGGERS)

    service_log = create_instance_by_class_name(
        session,
        ClassName.SERVICE_LOG,
        f"Build #{build_number} deployment log",
        "info",
        {
            "service": "ontology-core-service",
            "level": "info",
            "message": f"Mock deployment to {environment} finished successfully.",
            "build_number": build_number,
        },
    )
    relate(session, job.id, service_log.id, RelationType.PRODUCES_LOG)
    log = log_execution(
        session,
        "trigger_mock_jenkins",
        job.id,
        "success",
        int((perf_counter() - start) * 1000),
        f"Triggered mock Jenkins build #{build_number}.",
    )
    relate(session, job.id, log.id, RelationType.CONTAINS)
    return {"job": read_instance(job), "service_log": read_instance(service_log)}


def search_mock_logs(session: Session, service: str | None, level: str | None, q: str | None) -> dict:
    start = perf_counter()
    examples = [
        {
            "service": "ontology-core-service",
            "level": "info",
            "message": "Application started and ontology metadata loaded.",
        },
        {
            "service": "ontology-core-service",
            "level": "warning",
            "message": "Checklist found missing task relation for one feature.",
        },
        {
            "service": "ontology-worker",
            "level": "error",
            "message": "Mock adapter timeout while calling external webhook.",
        },
    ]
    matched = []
    for item in examples:
        if service and service not in item["service"]:
            continue
        if level and level != item["level"]:
            continue
        if q and q.lower() not in item["message"].lower():
            continue
        log_item = create_instance_by_class_name(
            session,
            ClassName.SERVICE_LOG,
            item["message"],
            item["level"],
            {**item, "mock": True},
        )
        matched.append(read_instance(log_item))
    log_execution(
        session,
        "search_mock_logs",
        None,
        "success",
        int((perf_counter() - start) * 1000),
        f"Found {len(matched)} mock log entries.",
    )
    return {"logs": matched}
