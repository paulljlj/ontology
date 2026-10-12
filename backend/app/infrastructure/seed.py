from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.ontology_service import create_instance_by_class_name, relate
from app.domain import ontology
from app.domain.constants import ClassName, RelationType
from app.infrastructure.orm import OntologyClassORM


def _owl_schema_for(class_name: str) -> dict:
    schema = ontology.get_schema(class_name)
    return {
        "required_fields": schema.get("required_fields", []),
        "optional_fields": schema.get("optional_fields", []),
        "description": schema.get("description", ""),
    }


def seed_database(session: Session) -> None:
    existing_names = set(session.scalars(select(OntologyClassORM.name)).all())
    for class_name in ontology.list_classes():
        if class_name not in existing_names:
            schema = _owl_schema_for(class_name)
            session.add(
                OntologyClassORM(
                    name=class_name,
                    description=schema["description"],
                    schema={
                        "required_fields": schema["required_fields"],
                        "optional_fields": schema["optional_fields"],
                        "teaching_note": f"{class_name} 的字段约束来自 OWL 本体，可按业务逐步扩展。",
                    },
                )
            )
    session.flush()

    project_class = session.scalar(
        select(OntologyClassORM).where(OntologyClassORM.name == ClassName.PROJECT)
    )
    if not project_class:
        return

    existing_project = project_class
    project_instance_exists = any(
        item.title == "Ontology AI Coding Demo" for item in existing_project.instances
    )
    if project_instance_exists:
        return

    project = create_instance_by_class_name(
        session,
        ClassName.PROJECT,
        "Ontology AI Coding Demo",
        "active",
        {
            "description": "演示用本体驱动 AI 软件工程平台。",
            "storage": "PostgreSQL",
        },
    )
    feature = create_instance_by_class_name(
        session,
        ClassName.FEATURE,
        "将存储从 PostgreSQL 扩展到 Neo4j",
        "idea",
        {
            "background": "希望未来能把拓扑关系切换到图数据库，同时保持 API 稳定。",
            "priority": "high",
        },
    )
    relate(session, project.id, feature.id, RelationType.CONTAINS)
