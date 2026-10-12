"""ETL: copy ontology classes, instances and relations from the SQL store to Neo4j.

Run with:
    python -m scripts.etl_to_neo4j
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session, joinedload  # noqa: E402

from app.domain import ontology  # noqa: E402
from app.infrastructure import graph_db  # noqa: E402
from app.infrastructure.database import session_scope  # noqa: E402
from app.infrastructure.orm import (  # noqa: E402
    OntologyClassORM,
    OntologyInstanceORM,
    OntologyRelationORM,
)


def _iter_classes(session: Session) -> Iterable[OntologyClassORM]:
    return session.scalars(select(OntologyClassORM).order_by(OntologyClassORM.name.asc()))


def _iter_instances(session: Session) -> Iterable[OntologyInstanceORM]:
    return session.scalars(
        select(OntologyInstanceORM)
        .options(joinedload(OntologyInstanceORM.ontology_class))
        .order_by(OntologyInstanceORM.created_at.asc())
    )


def _iter_relations(session: Session) -> Iterable[OntologyRelationORM]:
    return session.scalars(select(OntologyRelationORM).order_by(OntologyRelationORM.created_at.asc()))


def run() -> dict[str, int]:
    graph_db.verify_connectivity()
    graph_db.ensure_schema()
    counts = {"classes": 0, "instances": 0, "relations": 0}

    for class_name in ontology.list_classes():
        schema = ontology.get_schema(class_name)
        graph_db.upsert_class(class_name, schema.get("description", ""))
        counts["classes"] += 1

    with session_scope() as session:
        for row in _iter_classes(session):
            graph_db.upsert_class(row.name, row.description or "")
            counts["classes"] += 1

        for row in _iter_instances(session):
            graph_db.upsert_instance(
                instance_id=row.id,
                class_name=row.ontology_class.name,
                title=row.title,
                status=row.status,
                properties=row.properties or {},
                created_at=row.created_at.isoformat() if row.created_at else None,
                updated_at=row.updated_at.isoformat() if row.updated_at else None,
            )
            counts["instances"] += 1

        for row in _iter_relations(session):
            graph_db.relate_instances(
                relation_id=row.id,
                source_id=row.source_id,
                target_id=row.target_id,
                relation_type=row.type,
                properties=row.properties or {},
            )
            counts["relations"] += 1

    return counts


def main() -> int:
    try:
        counts = run()
    except Exception as exc:
        print(f"ETL failed: {exc}")
        return 1
    print(f"ETL ok: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())