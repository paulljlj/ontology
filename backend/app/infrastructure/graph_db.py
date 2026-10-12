"""Neo4j connection helpers and the graph-query repository used by ETL + read APIs."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from neo4j import Driver, GraphDatabase, Session

from app.infrastructure.config import settings


_driver: Driver | None = None


def get_driver() -> Driver:
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
    return _driver


def close_driver() -> None:
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None


@contextmanager
def graph_session(database: str | None = None) -> Session:
    session = get_driver().session(database=database or settings.neo4j_database)
    try:
        yield session
    finally:
        session.close()


def verify_connectivity() -> bool:
    with graph_session() as session:
        session.run("RETURN 1 AS ok").single()
    return True


_CONSTRAINT_STATEMENTS = [
    "CREATE CONSTRAINT ontology_instance_id IF NOT EXISTS FOR (n:OntologyInstance) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT ontology_class_name IF NOT EXISTS FOR (n:OntologyClass) REQUIRE n.name IS UNIQUE",
    "CREATE INDEX ontology_instance_class IF NOT EXISTS FOR (n:OntologyInstance) ON (n.class_name)",
    "CREATE INDEX ontology_instance_title IF NOT EXISTS FOR (n:OntologyInstance) ON (n.title)",
    "CREATE INDEX ontology_instance_status IF NOT EXISTS FOR (n:OntologyInstance) ON (n.status)",
]


def ensure_schema() -> None:
    with graph_session() as session:
        for statement in _CONSTRAINT_STATEMENTS:
            session.run(statement)


def upsert_class(name: str, description: str) -> None:
    with graph_session() as session:
        session.run(
            """
            MERGE (c:OntologyClass {name: $name})
            SET c.description = $description
            """,
            name=name,
            description=description,
        )


def upsert_instance(
    instance_id: str,
    class_name: str,
    title: str,
    status: str,
    properties: dict[str, Any],
    created_at: str | None,
    updated_at: str | None,
) -> None:
    with graph_session() as session:
        session.run(
            """
            MERGE (c:OntologyClass {name: $class_name})
            MERGE (i:OntologyInstance {id: $id})
            SET i.class_name = $class_name,
                i.title = $title,
                i.status = $status,
                i.properties_json = $properties_json,
                i.created_at = coalesce($created_at, i.created_at),
                i.updated_at = coalesce($updated_at, i.updated_at)
            MERGE (i)-[:OF_CLASS]->(c)
            """,
            id=instance_id,
            class_name=class_name,
            title=title,
            status=status,
            properties_json=_serialize(properties),
            created_at=created_at,
            updated_at=updated_at,
        )


def relate_instances(
    relation_id: str,
    source_id: str,
    target_id: str,
    relation_type: str,
    properties: dict[str, Any],
) -> None:
    with graph_session() as session:
        session.run(
            f"""
            MATCH (s:OntologyInstance {{id: $source_id}})
            MATCH (t:OntologyInstance {{id: $target_id}})
            MERGE (s)-[r:{relation_type} {{id: $relation_id}}]->(t)
            SET r.properties_json = $properties_json
            """,
            source_id=source_id,
            target_id=target_id,
            relation_id=relation_id,
            properties_json=_serialize(properties),
        )


def upsert_inferred_edge(
    source_id: str,
    target_id: str,
    relation_type: str,
    reason: str,
) -> None:
    """Idempotently write an inferred edge (Pellet-derived) with a deterministic id."""
    edge_id = f"infer:{relation_type}:{source_id}:{target_id}"
    with graph_session() as session:
        session.run(
            f"""
            MATCH (s:OntologyInstance {{id: $source_id}})
            MATCH (t:OntologyInstance {{id: $target_id}})
            MERGE (s)-[r:{relation_type} {{id: $edge_id}}]->(t)
            SET r.inferred = true,
                r.reason = $reason,
                r.properties_json = $properties_json
            """,
            source_id=source_id,
            target_id=target_id,
            edge_id=edge_id,
            reason=reason,
            properties_json=_serialize({"inferred": True, "reason": reason}),
        )


def clear_inferred_edges() -> int:
    """Drop all inferred edges before re-materializing. Returns the number removed."""
    with graph_session() as session:
        result = session.run(
            "MATCH ()-[r]->() WHERE r.inferred = true DELETE r RETURN count(r) AS n"
        ).single()
        return int(result["n"]) if result else 0


def fetch_graph(root_id: str | None = None, depth: int = 3, limit: int = 80) -> dict[str, list[dict[str, Any]]]:
    bounded_depth = max(1, min(int(depth), 6))
    with graph_session() as session:
        if root_id:
            result = session.run(
                f"""
                MATCH (root:OntologyInstance {{id: $root_id}})
                MATCH path = (root)-[*1..{bounded_depth}]-(neighbor:OntologyInstance)
                WITH collect(DISTINCT neighbor) AS nodes
                UNWIND nodes AS n
                OPTIONAL MATCH (n)-[r]->(m:OntologyInstance)
                WHERE m IN nodes
                WITH nodes, collect(DISTINCT r) AS edges
                RETURN nodes, edges
                """,
                root_id=root_id,
            ).single()
        else:
            result = session.run(
                """
                MATCH (n:OntologyInstance)
                WITH n ORDER BY n.created_at ASC LIMIT $limit
                WITH collect(n) AS nodes
                UNWIND nodes AS n
                OPTIONAL MATCH (n)-[r]->(m:OntologyInstance)
                WHERE m IN nodes
                RETURN nodes, collect(DISTINCT r) AS edges
                """,
                limit=limit,
            ).single()

        nodes = [_node_to_dict(record) for record in (result["nodes"] if result else [])]
        edges = [_edge_to_dict(record) for record in (result["edges"] if result and result["edges"] else []) if record is not None]
        return {"nodes": nodes, "edges": edges}


def query_subgraph(class_name: str, limit: int = 50) -> list[dict[str, Any]]:
    with graph_session() as session:
        result = session.run(
            """
            MATCH (n:OntologyInstance {class_name: $class_name})
            OPTIONAL MATCH (n)-[r]->(m:OntologyInstance)
            RETURN n, collect({rel: type(r), target_id: m.id}) AS relations
            LIMIT $limit
            """,
            class_name=class_name,
            limit=limit,
        )
        return [_projection_to_dict(record) for record in result]


def _serialize(properties: dict[str, Any]) -> str:
    import json

    return json.dumps(properties or {}, ensure_ascii=False, default=str)


def _deserialize(value: Any) -> Any:
    import json

    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _node_to_dict(record: Any) -> dict[str, Any]:
    return {
        "id": record["id"],
        "class_name": record["class_name"],
        "title": record["title"],
        "status": record.get("status", "draft"),
        "properties": _deserialize(record.get("properties_json", "{}")),
    }


def _edge_to_dict(record: Any) -> dict[str, Any]:
    properties = _deserialize(record.get("properties_json", "{}"))
    raw_id = record.get("id")
    if raw_id is None:
        raw_id = getattr(record, "id", None)
    return {
        "id": str(raw_id) if raw_id is not None else None,
        "source_id": record.start_node["id"],
        "target_id": record.end_node["id"],
        "type": record.type,
        "properties": properties,
        "inferred": bool(properties.get("inferred")) or bool(record.get("inferred", False)),
    }


def _projection_to_dict(record: Any) -> dict[str, Any]:
    node = record["n"]
    relations = [
        {"type": item.get("rel"), "target_id": item.get("target_id")}
        for item in (record["relations"] or [])
        if item.get("rel")
    ]
    return {
        "id": node["id"],
        "class_name": node["class_name"],
        "title": node["title"],
        "status": node.get("status", "draft"),
        "properties": _deserialize(node.get("properties_json", "{}")),
        "relations": relations,
    }