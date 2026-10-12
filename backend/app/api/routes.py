from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.ontology_service import (
    create_instance,
    create_relation,
    get_graph,
    get_instance_or_404,
    list_instances,
    patch_instance,
    read_instance,
    read_relation,
)
from app.application.workflows import (
    generate_plan_from_spec,
    generate_spec_from_feature,
    generate_tasks_from_plan,
    run_checklist,
)
from app.domain import reasoner
from app.domain.schemas import (
    ChecklistRequest,
    GraphRead,
    InstanceCreate,
    InstancePatch,
    JenkinsTriggerRequest,
    LogSearchRequest,
    OntologyClassRead,
    OntologyInstanceRead,
    OntologyRelationRead,
    RelationCreate,
    WorkflowFeatureRequest,
    WorkflowPlanRequest,
    WorkflowSpecRequest,
)
from app.infrastructure import graph_db
from app.infrastructure.database import get_session, session_scope
from app.infrastructure.mock_integrations import search_mock_logs, trigger_mock_jenkins
from app.infrastructure.orm import OntologyClassORM, OntologyInstanceORM, OntologyRelationORM

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/classes", response_model=list[OntologyClassRead])
def get_classes(session: Session = Depends(get_session)):
    return session.scalars(select(OntologyClassORM).order_by(OntologyClassORM.name.asc())).all()


@router.get("/instances", response_model=list[OntologyInstanceRead])
def get_instances(
    class_name: str | None = Query(default=None, alias="class"),
    q: str | None = None,
    status: str | None = None,
    session: Session = Depends(get_session),
):
    return list_instances(session, class_name=class_name, q=q, status=status)


@router.post("/instances", response_model=OntologyInstanceRead)
def post_instance(payload: InstanceCreate, session: Session = Depends(get_session)):
    instance = create_instance(session, payload)
    result = read_instance(instance)
    session.commit()
    return result


@router.get("/instances/{instance_id}", response_model=OntologyInstanceRead)
def get_instance(instance_id: str, session: Session = Depends(get_session)):
    return read_instance(get_instance_or_404(session, instance_id))


@router.patch("/instances/{instance_id}", response_model=OntologyInstanceRead)
def update_instance(instance_id: str, payload: InstancePatch, session: Session = Depends(get_session)):
    instance = patch_instance(session, instance_id, payload)
    result = read_instance(instance)
    session.commit()
    return result


@router.post("/relations", response_model=OntologyRelationRead)
def post_relation(payload: RelationCreate, session: Session = Depends(get_session)):
    relation = create_relation(session, payload)
    result = read_relation(relation)
    session.commit()
    return result


@router.get("/graph", response_model=GraphRead)
def graph(root_id: str | None = None, session: Session = Depends(get_session)):
    return get_graph(session, root_id=root_id)


@router.post("/workflows/spec-from-feature")
def workflow_spec_from_feature(
    payload: WorkflowFeatureRequest,
    require_feishu_approval: bool = Query(default=False, description="开启飞书审批门禁：Spec 停在 pending_review，需飞书同意后才会继续生成 Plan/Tasks"),
    session: Session = Depends(get_session),
):
    result = generate_spec_from_feature(
        session, payload.feature_id, require_feishu_approval=require_feishu_approval,
    )
    session.commit()
    return result


@router.post("/workflows/plan-from-spec")
def workflow_plan_from_spec(payload: WorkflowSpecRequest, session: Session = Depends(get_session)):
    result = generate_plan_from_spec(session, payload.spec_id)
    session.commit()
    return result


@router.post("/workflows/tasks-from-plan")
def workflow_tasks_from_plan(payload: WorkflowPlanRequest, session: Session = Depends(get_session)):
    result = generate_tasks_from_plan(session, payload.plan_id)
    session.commit()
    return result


@router.post("/workflows/run-checklist")
def workflow_run_checklist(payload: ChecklistRequest, session: Session = Depends(get_session)):
    result = run_checklist(session, payload.root_id)
    session.commit()
    return result


@router.post("/integrations/jenkins/trigger")
def jenkins_trigger(payload: JenkinsTriggerRequest, session: Session = Depends(get_session)):
    result = trigger_mock_jenkins(
        session,
        job_id=payload.job_id,
        feature_id=payload.feature_id,
        environment=payload.environment,
    )
    session.commit()
    return result


@router.post("/integrations/logs/search")
def logs_search(payload: LogSearchRequest, session: Session = Depends(get_session)):
    result = search_mock_logs(session, service=payload.service, level=payload.level, q=payload.q)
    session.commit()
    return result


@router.post("/reasoning/materialize")
def materialize_inferred():
    """Run Pellet over the SQL graph and write inferred (transitive) edges to Neo4j."""
    graph_db.verify_connectivity()
    removed = graph_db.clear_inferred_edges()

    instances: list[dict] = []
    relations: list[dict] = []
    with session_scope() as session:
        for row in session.scalars(select(OntologyInstanceORM)).all():
            instances.append(
                {
                    "id": row.id,
                    "class_name": row.ontology_class.name,
                    "title": row.title,
                    "status": row.status,
                    "properties": row.properties or {},
                }
            )
        for row in session.scalars(select(OntologyRelationORM)).all():
            relations.append(
                {
                    "id": row.id,
                    "source_id": row.source_id,
                    "target_id": row.target_id,
                    "type": row.type,
                    "properties": row.properties or {},
                }
            )

    inferred = reasoner.compute_inferred_edges(instances, relations)
    for edge in inferred:
        graph_db.upsert_inferred_edge(
            source_id=edge["source_id"],
            target_id=edge["target_id"],
            relation_type=edge["type"],
            reason=edge.get("reason", "transitive_closure"),
        )

    return {"removed": removed, "computed": len(inferred), "instances": len(instances), "relations": len(relations)}
