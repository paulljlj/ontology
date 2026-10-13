"""MCP server exposing ontology tools over the FastMCP stdio transport."""

import sys
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp.server.fastmcp import FastMCP  # noqa: E402
from pydantic import Field  # noqa: E402

from app.application import ontology_service, workflows  # noqa: E402
from app.application.report_workflow import (  # noqa: E402
    ARTIFACT_ROOT,
    create_workflow_run,
    execute_workflow_run,
    get_workflow_snapshot,
    profile_tables,
)
from app.application.ontology_service import (  # noqa: E402
    read_instance,
    read_relation,
    split_declared_and_extra,
)
from app.domain import ontology, reasoner  # noqa: E402
from app.domain.constants import ClassName, RelationType  # noqa: E402
from app.infrastructure import graph_db, mock_integrations  # noqa: E402
from app.infrastructure.config import settings  # noqa: E402
from app.infrastructure.database import session_scope  # noqa: E402
from app.infrastructure.orm import ApprovalMappingORM  # noqa: E402
from app.infrastructure.orm import new_id  # noqa: E402
from app.infrastructure.tabular_files import read_tabular  # noqa: E402


mcp = FastMCP("ontology-ai", instructions="Tools backed by the ontology platform.")


def _normalize_node(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record.get("id"),
        "class_name": record.get("class_name", ""),
        "title": record.get("title", ""),
        "status": record.get("status", "draft"),
        "properties": record.get("properties", {}) or {},
    }


def _normalize_edge(record: dict[str, Any]) -> dict[str, Any]:
    properties = record.get("properties", {}) or {}
    return {
        "id": record.get("id"),
        "source_id": record.get("source_id"),
        "target_id": record.get("target_id"),
        "type": record.get("type"),
        "properties": properties,
        "inferred": bool(record.get("inferred")) or bool(properties.get("inferred")),
        "reason": properties.get("reason"),
    }


@mcp.tool(structured_output=False)
def search_ontology(query: str = Field(...), class_name: str | None = None, status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """Search instances in the ontology."""
    with session_scope() as session:
        items = ontology_service.list_instances(session, class_name=class_name, q=query, status=status)
    return [item.model_dump(mode="json") for item in items[:limit]]


@mcp.tool(structured_output=False)
def describe_class(class_name: str = Field(...)) -> dict[str, Any]:
    """Return the OWL-derived schema for a class."""
    if ontology.get_class(class_name) is None:
        raise ValueError(f"Class not found: {class_name}")
    schema = ontology.get_schema(class_name)
    relations = []
    for relation_type, info in {
        relation: ontology.get_relation_schema(relation)
        for relation in ontology.list_relations()
    }.items():
        if class_name in info.get("domain", []) or class_name in info.get("range", []):
            relations.append({"name": relation_type, **info})
    return {
        "class_name": class_name,
        "description": schema.get("description", ""),
        "required_fields": schema.get("required_fields", []),
        "optional_fields": schema.get("optional_fields", []),
        "relations": relations,
    }


@mcp.tool(structured_output=False)
def create_instance(
    class_name: str = Field(...),
    title: str = Field(...),
    status: str = "draft",
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a new ontology instance after running OWL validation."""
    if ontology.get_class(class_name) is None:
        raise ValueError(f"Class not found: {class_name}")
    properties = properties or {}
    validation = reasoner.validate_instance(class_name, title, status, properties)
    if not validation.ok:
        raise ValueError({"message": "本体实例校验失败", "errors": validation.errors})
    with session_scope() as session:
        instance = ontology_service.create_instance_by_class_name(session, class_name, title, status, properties)
        graph_db.upsert_instance(
            instance_id=instance.id,
            class_name=class_name,
            title=title,
            status=status,
            properties=properties,
            created_at=instance.created_at.isoformat() if instance.created_at else None,
            updated_at=instance.updated_at.isoformat() if instance.updated_at else None,
        )
        graph_db.upsert_class(class_name, ontology.get_schema(class_name).get("description", ""))
        payload = read_instance(instance).model_dump(mode="json")
    return payload


@mcp.tool(structured_output=False)
def relate(source_id: str = Field(...), target_id: str = Field(...), relation_type: str = Field(...), properties: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create a relation between two instances."""
    properties = properties or {}
    with session_scope() as session:
        source = ontology_service.get_instance_or_404(session, source_id)
        target = ontology_service.get_instance_or_404(session, target_id)
        validation = reasoner.validate_relation(
            relation_type,
            source.ontology_class.name,
            target.ontology_class.name,
        )
        if not validation.ok:
            raise ValueError({"message": "本体关系校验失败", "errors": validation.errors})
        relation = ontology_service.relate(session, source_id, target_id, relation_type, properties)
        graph_db.relate_instances(
            relation_id=relation.id,
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            properties=properties,
        )
        payload = read_relation(relation).model_dump(mode="json")
    return payload


@mcp.tool(structured_output=False)
def query_graph(root_id: str | None = None, depth: int = 3, limit: int = 80) -> dict[str, Any]:
    """Return a sub-graph rooted at root_id (or the first N instances if root_id is omitted)."""
    raw = graph_db.fetch_graph(root_id=root_id, depth=depth, limit=limit)
    return {
        "nodes": [_normalize_node(item) for item in raw["nodes"]],
        "edges": [_normalize_edge(item) for item in raw["edges"]],
    }


@mcp.tool(structured_output=False)
def search_logs(service: str | None = None, level: str | None = None, q: str | None = None) -> list[dict[str, Any]]:
    """Run the mock log integration and return matched log instances."""
    with session_scope() as session:
        result = mock_integrations.search_mock_logs(session, service=service, level=level, q=q)
    return [item.model_dump(mode="json") for item in result.get("logs", [])]


@mcp.tool(structured_output=False)
def trigger_jenkins(feature_id: str | None = None, environment: str = "staging") -> dict[str, Any]:
    """Trigger the mock Jenkins job for a Feature."""
    if feature_id is None:
        raise ValueError("feature_id is required for trigger_jenkins")
    with session_scope() as session:
        result = mock_integrations.trigger_mock_jenkins(session, job_id=None, feature_id=feature_id, environment=environment)
    return {key: value.model_dump(mode="json") for key, value in result.items() if hasattr(value, "model_dump")}


@mcp.tool(structured_output=False)
def inspect_tabular_file(path: str = Field(...)) -> dict[str, Any]:
    """Inspect one workspace CSV/XLSX file and return its schema and quality profile."""
    source = _safe_workspace_table(path)
    tables = read_tabular(source)
    return {
        "file": source.name,
        "tables": [
            {"name": table.name, "headers": table.headers, "rows": len(table.rows)} for table in tables
        ],
        "profile": profile_tables(tables),
    }


@mcp.tool(structured_output=False)
def execute_data_report(
    requirement: str = Field(...),
    input_paths: list[str] | None = None,
    title: str = "本体智能体执行",
) -> dict[str, Any]:
    """Compile and execute a Task DAG; source discovery is autonomous when paths are omitted."""
    if not requirement.strip():
        raise ValueError("requirement is required")
    run_id = new_id()
    input_directory = ARTIFACT_ROOT / run_id / "inputs"
    input_directory.mkdir(parents=True, exist_ok=True)
    inputs: list[dict[str, Any]] = []
    for path in input_paths or []:
        source = _safe_workspace_table(path)
        destination = input_directory / source.name
        if destination.exists():
            destination = input_directory / f"{source.stem}-{len(inputs) + 1}{source.suffix}"
        shutil.copy2(source, destination)
        inputs.append(
            {
                "name": source.name,
                "stored_name": destination.name,
                "path": str(destination.resolve()),
                "size": destination.stat().st_size,
                "content_type": "text/csv" if source.suffix.lower() == ".csv" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            }
        )
    create_workflow_run(requirement, title, inputs, run_id=run_id)
    execute_workflow_run(run_id)
    return get_workflow_snapshot(run_id)


@mcp.tool(structured_output=False)
def get_execution_run(run_id: str = Field(...)) -> dict[str, Any]:
    """Return Task, Skill, evidence, status, and artifacts for a WorkflowRun."""
    return get_workflow_snapshot(run_id)


def _safe_workspace_table(path: str) -> Path:
    source = Path(path).expanduser().resolve()
    workspace_root = ROOT.parent.resolve()
    try:
        source.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError("Data tools may only read CSV/XLSX files inside the workspace") from exc
    if source.suffix.lower() not in {".csv", ".xlsx"} or not source.is_file():
        raise ValueError("Input must be an existing workspace CSV or XLSX file")
    return source


@mcp.tool(structured_output=False)
def send_feishu_message(
    chat_id: str = Field(...),
    content: str = Field(...),
    related_instance_id: str | None = None,
) -> dict[str, Any]:
    """Send a Feishu (Lark) text message; creates a FeishuMessage instance on success.

    Args:
        chat_id: recipient open_id or chat_id.
        content: text body.
        related_instance_id: optional ontology instance id (e.g. Task, JenkinsJob)
            — when given, a CONTAINS relation is added from it to the new
            FeishuMessage, so the message shows up under that artifact in the graph.

    Returns:
        ``{message: OntologyInstanceRead, feishu_response: {...}}``
    """
    from app.infrastructure import feishu_client

    if not chat_id or not content:
        raise ValueError("chat_id and content are required")
    send_result = feishu_client.send_message(chat_id, content)
    status_str = "sent" if send_result.get("status") == "ok" else "failed"
    full_properties: dict[str, Any] = {
        "chat_id": chat_id,
        "content": content,
        "sent_at": datetime.now(UTC).isoformat(),
        "via": send_result.get("via", "unknown"),
        "message_id": send_result.get("message_id"),
        "mock": send_result.get("via") == "mock",
    }
    if send_result.get("status") != "ok":
        full_properties["error"] = send_result.get("detail") or send_result.get("status")

    core_props, extras = split_declared_and_extra(ClassName.FEISHU_MESSAGE, full_properties)

    with session_scope() as session:
        msg = ontology_service.create_instance_by_class_name(
            session,
            ClassName.FEISHU_MESSAGE,
            title=content[:100],
            status=status_str,
            properties=core_props,
        )
        if extras:
            msg.properties = {**(msg.properties or {}), **extras}
            session.flush()
        # 把 ORM 实例的关键字段快照成纯值，session 关闭后用
        msg_id_local = msg.id
        msg_title_local = msg.title
        msg_created_at_local = msg.created_at.isoformat() if msg.created_at else None
        msg_updated_at_local = msg.updated_at.isoformat() if msg.updated_at else None

        # 先 upsert 到 Neo4j（如果有关联实例，先确保源端也存在），再 relate —
        # relate_instances 的 Cypher 依赖两侧节点都已 MERGE，顺序反了会丢关系。
        graph_db.upsert_instance(
            instance_id=msg_id_local,
            class_name=ClassName.FEISHU_MESSAGE,
            title=msg_title_local,
            status=status_str,
            properties=full_properties,
            created_at=msg_created_at_local,
            updated_at=msg_updated_at_local,
        )
        if related_instance_id:
            try:
                ontology_service.relate(
                    session,
                    related_instance_id,
                    msg_id_local,
                    RelationType.CONTAINS,
                    properties={"via": "feishu_message"},
                )
            except Exception as exc:
                # Relation failure should not break message creation
                print(f"[MCP] relate FeishuMessage → instance failed: {exc}")
        payload = read_instance(msg).model_dump(mode="json")
    return {"message": payload, "feishu_response": send_result}


@mcp.tool(structured_output=False)
def create_spec_approval(
    spec_id: str = Field(...),
    approver_open_id: str = "",
) -> dict[str, Any]:
    """Create a Feishu approval instance for a Spec.

    The Spec stays in ``draft`` until the approver clicks APPROVED in Feishu;
    the WebSocket listener (or polling fallback) then patches the Spec to
    ``ready`` and writes a Reflection.

    Args:
        spec_id: id of the Spec instance to send for review.
        approver_open_id: optional Feishu open_id of the approver. Falls back
            to ``settings.feishu_default_approver`` when empty.

    Returns:
        ``{spec_id, approval: {...}, feishu_message_id, via}``
    """
    from app.infrastructure import feishu_client, feishu_events

    with session_scope() as session:
        spec = ontology_service.get_instance_or_404(session, spec_id)
        if spec.ontology_class.name != ClassName.SPEC:
            raise ValueError(
                f"Instance {spec_id} is not a Spec (class={spec.ontology_class.name})"
            )

        # 把所有用到的 spec 字段提前快照成本地值，避免 session 关闭后访问 detached 实例
        spec_id_local = spec.id
        spec_title_local = spec.title
        spec_props = dict(spec.properties or {})

        form = feishu_client.build_spec_approval_form(
            spec_title=spec_title_local,
            spec_goal=spec_props.get("goal", ""),
            spec_version=spec_props.get("version", ""),
            spec_background=spec_props.get("background", ""),
        )
        approval_code = settings.feishu_approval_code or "MOCK_TEMPLATE"
        approver = approver_open_id or settings.feishu_default_approver or "ou_mock_approver"

        approval_result = feishu_client.create_approval(
            approval_code=approval_code,
            user_id=approver,
            form=form,
        )
        instance_code = approval_result.get("instance_code") or ""

        # 持久化映射 + 写 FeishuMessage 实例
        mapping = ApprovalMappingORM(
            spec_id=spec_id_local,
            instance_code=instance_code,
            status="PENDING",
            approver_open_id=approver,
        )
        session.add(mapping)
        session.flush()

        msg_full_props: dict[str, Any] = {
            "chat_id": approver,
            "content": f"已为 Spec '{spec_title_local}' 创建飞书审批（instance_code={instance_code}）",
            "sent_at": datetime.now(UTC).isoformat(),
            "via": approval_result.get("via", "unknown"),
            "approval_instance_code": instance_code,
            "mock": approval_result.get("via") == "mock",
        }
        core_props, extras = split_declared_and_extra(ClassName.FEISHU_MESSAGE, msg_full_props)
        feishu_msg = ontology_service.create_instance_by_class_name(
            session,
            ClassName.FEISHU_MESSAGE,
            title=f"Spec 审批: {spec_title_local}",
            status="pending",
            properties=core_props,
        )
        if extras:
            feishu_msg.properties = {**(feishu_msg.properties or {}), **extras}
            session.flush()

        # 捕获 feishu_msg 关键字段到本地
        feishu_msg_id_local = feishu_msg.id
        feishu_msg_title_local = feishu_msg.title
        feishu_msg_created_at_local = (
            feishu_msg.created_at.isoformat() if feishu_msg.created_at else None
        )

        # 先 upsert 到 Neo4j（保证 relate 时的目标节点存在），再 relate
        graph_db.upsert_instance(
            instance_id=feishu_msg_id_local,
            class_name=ClassName.FEISHU_MESSAGE,
            title=feishu_msg_title_local,
            status="pending",
            properties=msg_full_props,
            created_at=feishu_msg_created_at_local,
            updated_at=datetime.now(UTC).isoformat(),
        )
        ontology_service.relate(
            session,
            spec_id_local,
            feishu_msg_id_local,
            RelationType.CONTAINS,
            properties={"via": "spec_approval"},
        )

    feishu_events.register_mapping(spec_id_local, instance_code)

    return {
        "spec_id": spec_id_local,
        "approval": approval_result,
        "feishu_message_id": feishu_msg_id_local,
        "via": approval_result.get("via"),
    }


@mcp.tool(structured_output=False)
def check_approval_status(instance_code: str = Field(...)) -> dict[str, Any]:
    """Poll a Feishu approval instance and return its current status.

    Useful when WebSocket events aren't connected (e.g. local dev without
    lark_oapi installed). For a long-running watcher, prefer the background
    listener in ``app.infrastructure.feishu_events``.
    """
    from app.infrastructure import feishu_client

    if not instance_code:
        raise ValueError("instance_code is required")
    return feishu_client.get_approval_status(instance_code)


@mcp.resource("ontology://classes")
def list_classes_resource() -> dict[str, list[dict[str, Any]]]:
    return {"classes": [describe_class(name) for name in ontology.list_classes()]}


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
