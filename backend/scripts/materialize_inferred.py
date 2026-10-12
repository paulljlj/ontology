"""Run Pellet on the SQL graph and write inferred (transitive / sub-property) edges
into Neo4j with an ``inferred=true`` flag so the frontend can render them as dashed lines.

Run with:
    python -m scripts.materialize_inferred
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

from app.domain import reasoner  # noqa: E402
from app.infrastructure import graph_db  # noqa: E402
from app.infrastructure.database import session_scope  # noqa: E402
from app.infrastructure.orm import (  # noqa: E402
    OntologyInstanceORM,
    OntologyRelationORM,
)


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
    removed = graph_db.clear_inferred_edges()

    instances: list[dict] = []
    relations: list[dict] = []
    with session_scope() as session:
        for row in _iter_instances(session):
            instances.append(
                {
                    "id": row.id,
                    "class_name": row.ontology_class.name,
                    "title": row.title,
                    "status": row.status,
                    "properties": row.properties or {},
                }
            )
        for row in _iter_relations(session):
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


def main() -> int:
    try:
        counts = run()
    except Exception as exc:
        print(f"Materialize failed: {exc}")
        return 1
    print(f"Materialize ok: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())