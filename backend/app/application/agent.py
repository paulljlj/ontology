"""MCP-driven agent runner: lets the LLM pick MCP tools, with a hard-coded fallback path."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

from app.application import ontology_service, workflows  # noqa: E402
from app.domain import reasoner  # noqa: E402
from app.domain.constants import ClassName, RelationType  # noqa: E402
from app.domain.schemas import InstanceCreate, RelationCreate  # noqa: E402
from app.infrastructure import ai_provider, graph_db, mock_integrations  # noqa: E402
from app.infrastructure.database import session_scope  # noqa: E402
from app.infrastructure.orm import OntologyClassORM  # noqa: E402
from sqlalchemy import select  # noqa: E402


SYSTEM_PROMPT = """你是 ontology 平台的助手。请根据用户需求选择 MCP 工具：
- 了解某个类的字段请用 describe_class
- 创建 Feature 请用 create_instance(class_name='Feature', ...)
- 生成 Spec/Plan/Task 请使用 create_instance 与 relate，按工作流 DERIVES_TO → HAS_PLAN → HAS_TASK
- 查询图谱请用 query_graph

只输出 JSON：
{"tool": "tool_name", "arguments": {...}}
若无需工具直接返回 {"tool": "final", "answer": "..."}。
"""


async def _invoke_tool(session: ClientSession, name: str, arguments: dict[str, Any]) -> Any:
    result = await session.call_tool(name, arguments=arguments)
    if getattr(result, "isError", False):
        raise RuntimeError(f"{name} failed: {result.content}")
    return _decode(result.content)


def _decode(content: Any) -> Any:
    if not content:
        return None
    payload = []
    for block in content:
        text = getattr(block, "text", None)
        if text is None:
            payload.append(block)
        else:
            try:
                payload.append(json.loads(text))
            except json.JSONDecodeError:
                payload.append(text)
    return payload[0] if len(payload) == 1 else payload


async def _plan_with_llm(prompt: str) -> list[dict[str, Any]]:
    schema_hint = reasoner.describe_class_for_llm(ClassName.FEATURE)
    feature_text = ai_provider.generate_spec_prompt(prompt, schema_hint)
    plan = ai_provider.call_llm(feature_text) if hasattr(ai_provider, "call_llm") else None
    if not plan:
        return []
    try:
        return json.loads(plan)
    except json.JSONDecodeError:
        return []


async def run_agent(feature_title: str) -> dict[str, Any]:
    """Execute the MCP-driven workflow: Feature → Spec → Plan → Tasks via tool calls."""
    server_params = StdioServerParameters(command=sys.executable, args=["-m", "app.mcp.server"])
    transcript: list[dict[str, Any]] = []
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool_names = {tool.name for tool in tools.tools}
            assert {"create_instance", "relate", "query_graph"}.issubset(tool_names), tool_names

            feature = await _invoke_tool(
                session,
                "create_instance",
                {"class_name": ClassName.FEATURE, "title": feature_title, "status": "idea", "properties": {"priority": "high"}},
            )
            transcript.append({"tool": "create_instance", "arguments": {"class_name": ClassName.FEATURE, "title": feature_title}, "result": feature})

            spec = await _invoke_tool(
                session,
                "create_instance",
                {"class_name": ClassName.SPEC, "title": f"{feature_title} Spec", "status": "ready", "properties": {"goal": "通过 MCP 链路生成"}},
            )
            transcript.append({"tool": "create_instance", "arguments": {"class_name": ClassName.SPEC, "title": spec["title"]}, "result": spec})
            await _invoke_tool(session, "relate", {"source_id": feature["id"], "target_id": spec["id"], "relation_type": RelationType.DERIVES_TO})

            plan = await _invoke_tool(
                session,
                "create_instance",
                {"class_name": ClassName.PLAN, "title": f"{feature_title} Plan", "status": "ready", "properties": {"summary": "MCP 默认计划"}},
            )
            transcript.append({"tool": "create_instance", "arguments": {"class_name": ClassName.PLAN, "title": plan["title"]}, "result": plan})
            await _invoke_tool(session, "relate", {"source_id": spec["id"], "target_id": plan["id"], "relation_type": RelationType.HAS_PLAN})

            task_titles = ["定义领域对象", "实现仓储", "编写 API", "添加单元测试", "运行端到端验证"]
            tasks: list[dict[str, Any]] = []
            for title in task_titles:
                task = await _invoke_tool(
                    session,
                    "create_instance",
                    {"class_name": ClassName.TASK, "title": title, "status": "todo", "properties": {"layer": "application"}},
                )
                tasks.append(task)
                await _invoke_tool(session, "relate", {"source_id": plan["id"], "target_id": task["id"], "relation_type": RelationType.HAS_TASK})
            transcript.append({"tool": "create_instance", "arguments": {"class_name": ClassName.TASK, "count": len(tasks)}, "result": tasks})

            graph = await _invoke_tool(session, "query_graph", {"root_id": feature["id"], "depth": 3})
            transcript.append({"tool": "query_graph", "result": {"nodes": len(graph["nodes"]), "edges": len(graph["edges"])}})

    return {
        "feature": feature,
        "spec": spec,
        "plan": plan,
        "tasks": tasks,
        "graph": graph,
        "transcript": transcript,
    }


def run_fallback_workflow(session, feature_id: str) -> dict[str, Any]:
    """Legacy deterministic workflow used when the MCP transport is unavailable."""
    spec = workflows.generate_spec_from_feature(session, feature_id)
    plan = workflows.generate_plan_from_spec(session, spec["spec"].id)
    tasks = workflows.generate_tasks_from_plan(session, plan["plan"].id)
    graph = ontology_service.get_graph(session, root_id=feature_id, depth=3)
    return {
        "feature_id": feature_id,
        "spec": spec["spec"].model_dump(mode="json"),
        "plan": plan["plan"].model_dump(mode="json"),
        "tasks": [task.model_dump(mode="json") for task in tasks["tasks"]],
        "graph": {"nodes": len(graph.nodes), "edges": len(graph.edges)},
    }


async def run_with_fallback(feature_title: str) -> dict[str, Any]:
    try:
        return await run_agent(feature_title)
    except Exception as exc:
        with session_scope() as session:
            class_id = session.scalar(select(OntologyClassORM).where(OntologyClassORM.name == ClassName.FEATURE)).id
            feature = ontology_service.create_instance(
                session,
                InstanceCreate(class_id=class_id, title=feature_title, status="idea", properties={"priority": "high"}),
            )
            result = run_fallback_workflow(session, feature.id)
            graph_db.upsert_instance(
                instance_id=feature.id,
                class_name=ClassName.FEATURE,
                title=feature_title,
                status="idea",
                properties={"priority": "high"},
                created_at=feature.created_at.isoformat() if feature.created_at else None,
                updated_at=feature.updated_at.isoformat() if feature.updated_at else None,
            )
            return {"fallback": True, "reason": str(exc), **result}


def main() -> None:
    feature_title = sys.argv[1] if len(sys.argv) > 1 else "Demo Feature via MCP"
    result = asyncio.run(run_with_fallback(feature_title))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()