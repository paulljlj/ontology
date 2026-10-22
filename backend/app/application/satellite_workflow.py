"""Satellite diagnosis and route-planning workflow with traceable processors."""
from __future__ import annotations
import asyncio
from contextlib import AsyncExitStack
from datetime import datetime, timedelta, timezone
import hashlib
from html import escape
import json
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select, update
from app.domain.satellite_schemas import SatelliteRunCreate
from app.domain.satellite_rules import validate_network_entities
from app.infrastructure.database import session_scope
from app.infrastructure.orm import WorkflowRunORM, ExecutionTaskORM, ArtifactORM, new_id
from app.infrastructure.satellite_config import data_root, artifact_root, mcp_config
from app.infrastructure.satellite_data import load_case, parse_time
from app.infrastructure.mcp_gateway import McpGateway, describe_exception
from app.application.satellite_diagnosis_adapter import run_integrated_diagnosis
from app.application.satellite_routing import optimize_snapshot


def _time(value):
    return value.isoformat() if value is not None else None


def build_satellite_plan(payload: SatelliteRunCreate, mode: str) -> list[dict]:
    """A small rule-driven plan, not a claim of free-form LLM planning."""
    steps = [
        ("load_snapshot", "读取时点网络数据", "satellite.snapshot", "data.snapshot", "NET-SNAPSHOT", ["duckdb.execute_query"] if mode == "mcp" else []),
        ("validate_domain", "校验本体对象与关系", "satellite.ontology", "ontology.validate", "NET-TYPE / NET-ENDPOINT / NET-TIME", []),
    ]
    if payload.auto_diagnosis:
        bindings = ["neo4j.get-schema", "neo4j.read-cypher"] if payload.diagnosis_graph_backend == "neo4j_mcp" else []
        steps.append(("diagnose_network", "分析异常、候选原因与正常对照", "satellite.diagnosis.auto",
            "satellite.diagnosis", "DIAG-THRESHOLD / DIAG-TEMPORAL / DIAG-CONTROL", bindings))
    elif payload.diagnosis:
        steps.append(("accept_diagnosis", "校验外部诊断与证据引用", "satellite.diagnosis", "evidence.validate", "外部诊断必须同案例、同截止时间且证据可追溯", []))
    steps += [
        ("plan_routes", "联合验算备选通信路径", "satellite.routing", "network.reroute", "PLAN-PATH / PLAN-LOAD / PLAN-SLA", []),
        ("build_report", "汇总六部分报告", "satellite.report", "report.compose", "未启用诊断时明确标注，不将手动目标当根因", []),
        ("publish_report", "生成报告与结果文件", "satellite.publish", "artifact.write", "产物写入本次运行专属目录", ["filesystem.write_file"] if mode == "mcp" else []),
        ("verify_delivery", "检查产物和执行证据", "satellite.verify", "artifact.verify", "下载文件必须存在、可解析且与本次结果一致", ["filesystem.get_file_info"] if mode == "mcp" else []),
    ]
    plan = []
    for index, (key, title, processor, capability, rule, tools) in enumerate(steps):
        plan.append({"key": key, "title": title, "skill_spec": {
            "name": processor, "processor": processor, "version": "1.0", "generated_for_run": True,
            "required_capabilities": [capability], "mcp_bindings": tools,
            "depends_on": [steps[index - 1][0]] if index else [], "ontology_rule": rule,
            "parameters": {"source": "validated_run_contract",
                "diagnosis_graph_backend": payload.diagnosis_graph_backend if processor == "satellite.diagnosis.auto" else None},
            "permission_policy": "observation-read/artifact-scoped-write",
        }})
    return plan


def create_satellite_run(payload: SatelliteRunCreate) -> str:
    # Validate caller IDs and times before returning 202, with no MCP launch.
    snapshot = load_case(data_root(), payload.case_id, at=_time(payload.at), as_of=_time(payload.as_of))
    if payload.auto_diagnosis and not (parse_time(snapshot["case"]["analysis_start"]) <= parse_time(snapshot["at"])
            < parse_time(snapshot["case"]["analysis_end_exclusive"])):
        raise ValueError("自动诊断的评估时刻必须位于案例分析窗口内")
    unknown = set(payload.avoid_objects) - set(snapshot["nodes"]) - set(snapshot["links"])
    if unknown:
        raise ValueError("未知待避对象：" + ", ".join(sorted(unknown)))
    if payload.service_ids and set(payload.service_ids) - set(snapshot["services"]):
        raise ValueError("存在未知业务ID")
    if payload.diagnosis:
        validate_diagnosis(payload, snapshot)
    mode = mcp_config().get("default_mode", "file")
    plan = build_satellite_plan(payload, mode)
    identity = new_id()
    with session_scope() as session:
        session.add(WorkflowRunORM(id=identity, workflow_type="satellite_planning", title="卫星网络备选路径与证据报告",
            requirement=payload.requirement, status="planning", input_files=[{"name": "satellite_demo_v1/observed", "size": 0}],
            result_contract={"case_id": payload.case_id, "avoid_objects": payload.avoid_objects,
                "at": snapshot["at"], "as_of": snapshot["as_of"], "execution_mode": mode,
                "request": payload.model_dump(mode="json"), "rule_version": "satellite-planning-v2"},
            summary={"progress": 0, "task_count": len(plan), "diagnosis_status":
                "auto_pending" if payload.auto_diagnosis else ("provided" if payload.diagnosis else "pending")}))
        session.flush()
        for index, step in enumerate(plan, 1):
            session.add(ExecutionTaskORM(run_id=identity, task_key=step["key"], order_index=index,
                title=step["title"], description=step["skill_spec"]["ontology_rule"], status="pending",
                skill_spec=step["skill_spec"], inputs=[], outputs=[], evidence={}))
    return identity


def validate_diagnosis(payload: SatelliteRunCreate, snapshot: dict, diagnosis=None) -> dict:
    diagnosis = diagnosis or payload.diagnosis
    if diagnosis is None:
        return {"status": "pending", "verified_references": 0}
    cutoff = parse_time(snapshot["as_of"])
    if diagnosis.case_id != snapshot["case"]["case_id"] or diagnosis.as_of > cutoff:
        raise ValueError("外部诊断与本次案例/证据截止时间不一致")
    snapshot_end = parse_time(snapshot["at"]) + timedelta(seconds=snapshot["sampling_seconds"])
    if diagnosis.analysis_start < parse_time(snapshot["case"]["sample_start"]) or diagnosis.analysis_end > min(cutoff, snapshot_end):
        raise ValueError("外部诊断分析时段超出本次数据范围")
    ids = set(snapshot["nodes"]) | set(snapshot["links"])
    if any(c.object_id not in ids for c in diagnosis.causes):
        raise ValueError("外部诊断包含未知候选对象")
    for cause in diagnosis.causes:
        actual_type = "link" if cause.object_id in snapshot["links"] else snapshot["nodes"][cause.object_id]["node_type"]
        if cause.object_type != actual_type:
            raise ValueError("外部诊断候选对象类型与本体对象不一致：" + cause.object_id)
    requested_tables = {Path(ref.source_file).stem for ref in diagnosis.evidence}
    evidence_index: dict[str, set[tuple[str, str, datetime, datetime]]] = {}
    for table in requested_tables:
        entries: set[tuple[str, str, datetime, datetime]] = set()
        for row in snapshot.get("tables", {}).get(table, []):
            stamp = row.get("timestamp") or row.get("event_start")
            available = row.get("available_at")
            if not stamp or not available:
                continue
            record_ids = {str(row[k]) for k in ("sample_id", "event_id", "route_id", "service_id", "node_id", "link_id") if row.get(k)}
            object_ids = {str(row[k]) for k in ("node_id", "link_id", "service_id", "source_satellite_id", "object_id") if row.get(k)}
            parsed_stamp, parsed_available = parse_time(stamp), parse_time(available)
            entries.update((record_id, object_id, parsed_stamp, parsed_available)
                           for record_id in record_ids for object_id in object_ids)
        evidence_index[table] = entries
    for ref in diagnosis.evidence:
        if ref.timestamp > parse_time(snapshot["at"]):
            raise ValueError("诊断证据发生时间晚于本次快照：" + ref.evidence_id)
        table = Path(ref.source_file).stem
        if (ref.record_id, ref.object_id, ref.timestamp, ref.available_at) not in evidence_index.get(table, set()):
            raise ValueError(f"诊断证据无法在本次可知观测中核对：{ref.evidence_id}")
    return {"status": "references_verified_not_causal_confirmation", "verified_references": len(diagnosis.evidence),
        "source": diagnosis.source, "evidence": [e.model_dump(mode="json") for e in diagnosis.evidence]}


def _task_state(run_id, key, status, evidence=None, outputs=None, error=""):
    with session_scope() as session:
        task = session.scalar(select(ExecutionTaskORM).where(ExecutionTaskORM.run_id == run_id, ExecutionTaskORM.task_key == key))
        if task is None:
            raise RuntimeError("执行步骤不存在")
        task.status, task.error = status, error
        if status == "running": task.started_at = datetime.now(timezone.utc)
        if status in {"succeeded", "failed"}: task.completed_at = datetime.now(timezone.utc)
        if evidence is not None: task.evidence = evidence
        if outputs is not None: task.outputs = outputs


async def _snapshot(context, spec):
    payload = context["payload"]
    if context["mode"] == "mcp":
        from app.infrastructure.satellite_mcp_data import load_mcp_snapshot
        snapshot = await load_mcp_snapshot(context["gateway"], data_root(), payload.case_id,
            at=context["contract"]["at"], as_of=context["contract"]["as_of"])
    else:
        snapshot = load_case(data_root(), payload.case_id, at=context["contract"]["at"], as_of=context["contract"]["as_of"])
    context["snapshot"] = snapshot
    return {"mode": context["mode"], "case_id": payload.case_id, "at": snapshot["at"], "as_of": snapshot["as_of"],
        "counts": {k: len(snapshot[k]) for k in ("nodes", "links", "services", "routes")},
        "limitation": "静态资产与接触计划来自已提供文件；未提供独立发布时间，按已知输入处理，不保证未来拓扑。"}


async def _ontology(context, spec):
    snapshot = context["snapshot"]
    checked = validate_network_entities(list(snapshot["nodes"].values()), list(snapshot["links"].values()))
    if not checked["ok"]:
        raise ValueError("本体约束不通过：" + "; ".join(checked["errors"])[:2000])
    context["ontology_validation"] = checked
    return {"checked": checked["checked"], "rule_facts": checked["rule_facts"], "rule_version": checked["rule_version"],
        "relations": checked["relations"], "limitations": checked.get("limitations", [])}


async def _diagnosis(context, spec):
    checked = validate_diagnosis(context["payload"], context["snapshot"])
    context["diagnosis"] = context["payload"].diagnosis
    context["diagnosis_origin"] = "external_json"
    context["avoid_objects"] = list(context["payload"].avoid_objects)
    context["diagnosis_validation"] = checked
    return checked


async def _auto_diagnosis(context, spec):
    payload = context["payload"]
    diagnosis, raw = await asyncio.to_thread(run_integrated_diagnosis, data_root(), context["snapshot"],
        graph_backend=payload.diagnosis_graph_backend)
    checked = validate_diagnosis(payload, context["snapshot"], diagnosis)
    inferred = [cause.object_id for cause in diagnosis.causes if cause.status == "supported"]
    context["diagnosis"] = diagnosis
    context["diagnosis_raw"] = raw
    context["diagnosis_origin"] = "integrated_module"
    context["diagnosis_validation"] = checked
    context["avoid_objects"] = list(payload.avoid_objects) if payload.avoid_objects else inferred
    return {**checked, "provider": "collaborator_satellite_diagnosis", "provider_schema_version": raw["schema_version"],
        "graph_backend": raw.get("graph_backend"), "major_count": raw["anomaly_overview"]["major_count"],
        "candidate_count": len(raw["root_cause_candidates"]), "watch_count": len(raw["minor_anomalies"].get("watch", [])),
        "priority_object": raw["conclusion_and_missing_evidence"].get("priority_object"),
        "selected_avoid_objects": context["avoid_objects"]}


async def _routing(context, spec):
    p = context["payload"]
    avoid_objects = context.get("avoid_objects", p.avoid_objects)
    result = optimize_snapshot(context["snapshot"], avoid_objects, service_ids=p.service_ids,
        max_utilization_pct=p.max_utilization_pct, max_latency_ms=p.max_latency_ms, max_options=p.max_options)
    context["routing"] = result
    return {"status": result["status"], "reason": result.get("reason", ""),
        "proposal_count": len(result["proposals"]), "evidence": result.get("evidence", []),
        "limitations": result.get("limitations", []), "search_limits": result.get("search_limits", {}),
        "rule_facts": [{"rule_id": key, "status": ("model_latency_checked_only" if key == "PLAN-SLA" else "model_checked")
            if result["status"] == "feasible" else "not_established"}
            for key in ("PLAN-PATH", "PLAN-LOAD", "PLAN-SLA")],
        "availability_sla": "not_evaluated_no_post_switch_observation"}


def compose_report(context: dict) -> dict:
    p, snapshot, routing = context["payload"], context["snapshot"], context["routing"]
    diagnosis = context.get("diagnosis") or p.diagnosis
    origin = context.get("diagnosis_origin", "external_json" if p.diagnosis else "manual")
    pending = "未启用自动诊断且未提供外部诊断；当前只展示原始观测和路径验算，不宣称已发现根因。"
    observations = [{"service_id": k, "source_satellite_id": row.get("source_satellite_id"),
        "timestamp": row.get("timestamp"), "availability_pct": row.get("availability_pct"),
        "sample_id": row.get("sample_id"), "measurement_status": row.get("measurement_status")}
        for k, row in snapshot["service_metrics"].items()]
    metrics = [{"label": "卫星", "value": sum(n["node_type"] == "satellite" for n in snapshot["nodes"].values()), "unit": "颗"},
        {"label": "地面站", "value": sum(n["node_type"] == "ground_station" for n in snapshot["nodes"].values()), "unit": "个"},
        {"label": "有向链路", "value": len(snapshot["links"]), "unit": "条"},
        {"label": "备选方案", "value": len(routing["proposals"]), "unit": "个"}]
    outcome = {"feasible": "找到满足当前容量余量和模型时延约束的备选方案。", "no_feasible_route": "当前条件下没有找到可行备选路径。",
        "insufficient_data": "关键观测不足，不能确认改路可行性。", "no_change_needed": "当前路由未经过指定待避对象，无需据此改路。"}.get(routing["status"], "请查看约束检查结果。")
    conclusions = [outcome, "路径模块使用人工条件或诊断模块的优先候选进行验算；候选仍不是已确认故障根因。",
        "所有结果来自模拟数据；路径只建议、不执行切换，可用度改善和真实因果关系尚未验证。"]
    missing = ["真实运行数据、实际切换后观测与人工确认的故障记录。"]
    if diagnosis:
        conclusions += diagnosis.conclusions
        missing += diagnosis.missing_evidence
        if diagnosis.source == "development_fixture": conclusions.insert(0, "外部诊断为开发测试样例，不能当作已交付算法的诊断结果。")
    else:
        missing.insert(0, "本次未启用自动诊断，也未提供外部诊断结果。")
    if routing.get("reason") and routing["status"] == "insufficient_data":
        missing.append("路径验算所需的完整当前观测：" + routing["reason"])
    display_routing = {**routing, "technical_limitations": routing.get("limitations", []), "limitations": [
        "待避对象是人工或外部诊断输入，不是本模块确认的根因。",
        "在限定数量的候选路径中搜索，不保证找到全网最优解。",
        "按当前业务请求量联合预留容量，结果不等于切换后实测吞吐量。",
        "时延来自简化传播、处理和排队模型；未验证改路后可用度。",
        "原有的其他瓶颈可能仍存在，方案不会声称解决全部网络问题。",
        "上游丢流后的背景负载采用保守预留；缺少关键数据时不强行给方案。",
        "仅建议备选路径，不执行任何真实设备切换。",
    ]}
    report = {"schema_version": "1.0", "dataset_kind": "synthetic", "case_id": p.case_id,
        "at": snapshot["at"], "as_of": snapshot["as_of"], "diagnosis_status": "provided" if diagnosis else "pending",
        "overview": {"summary": pending if not diagnosis else ("已运行同学交付的诊断模块并核对原始证据；原因候选不等于因果确认。"
                if origin == "integrated_module" else "已接收外部诊断；原始证据引用已核对，原因判断不等于独立因果确认。"),
            "metrics": metrics, "observations": observations, "external_summary": diagnosis.overview if diagnosis else {}},
        "causes": {"status": "provided" if diagnosis else "pending", "items": [c.model_dump() for c in diagnosis.causes] if diagnosis else [], "note": pending if not diagnosis else "来源为外部诊断，保留其支持、反对与缺失证据。"},
        "watch_items": {"status": "provided" if diagnosis else "pending", "items": diagnosis.watch_items if diagnosis else [], "note": pending if not diagnosis else "关注对象不等于必然故障。"},
        "route_options": display_routing,
        "impact": {"status": "provided" if diagnosis else "pending", "items": diagnosis.impact if diagnosis else [], "note": pending if not diagnosis else "正常对照分析来源为外部模块；路径方案另对共享资源进行约束检查。"},
        "conclusions": {"items": conclusions, "missing_evidence": missing},
        "provenance": {"input_source": "integrated_diagnosis" if origin == "integrated_module" else ("diagnosis_json" if diagnosis else "manual"),
            "diagnosis_provider": "collaborator_satellite_diagnosis" if origin == "integrated_module" else None,
            "diagnosis_graph_backend": context.get("diagnosis_raw", {}).get("graph_backend") if origin == "integrated_module" else None,
            "diagnosis_is_fixture": bool(diagnosis and diagnosis.source == "development_fixture"),
            "avoid_objects": context.get("avoid_objects", p.avoid_objects), "execution_mode": context["mode"], "rule_version": "satellite-planning-v2"},
        "evidence": [e.model_dump(mode="json") for e in diagnosis.evidence] if diagnosis else [],
        "ontology_validation": {"checked": context["ontology_validation"]["checked"], "rule_facts": context["ontology_validation"]["rule_facts"]},
        "topology": {"nodes": [{"id": k, "type": v["node_type"], "label": k} for k, v in snapshot["nodes"].items()],
            "edges": [{"id": k, "source": v["source_node_id"], "target": v["target_node_id"]} for k, v in snapshot["links"].items()]},
    }
    return report


async def _report(context, spec):
    context["report"] = compose_report(context)
    return {"diagnosis_status": context["report"]["diagnosis_status"], "sections": 6,
        "input_source": context["report"]["provenance"]["input_source"]}


def render_report_html(report: dict) -> str:
    """A standalone, escaped human-readable report; JSON remains the full contract."""
    def cell(value):
        if value is None:
            return "—"
        if isinstance(value, float):
            return f"{value:,.3f}".rstrip("0").rstrip(".")
        return escape(str(value))

    def bullets(items):
        return "<ul>" + "".join(f"<li>{cell(item)}</li>" for item in items) + "</ul>" if items else ""

    def details(value, title="查看结构化证据与完整字段"):
        return f"<details><summary>{cell(title)}</summary><pre>{escape(json.dumps(value, ensure_ascii=False, indent=2))}</pre></details>"

    def table(headers, rows):
        return '<div class="table"><table><thead><tr>' + "".join(f"<th>{cell(h)}</th>" for h in headers) + "</tr></thead><tbody>" + "".join(
            "<tr>" + "".join(f"<td>{cell(v)}</td>" for v in row) + "</tr>" for row in rows) + "</tbody></table></div>"

    def external(section):
        content = f"<p>{cell(section.get('note', ''))}</p>"
        for item in section.get("items", []):
            content += '<div class="item"><strong>' + cell(item.get("object_id") or item.get("service_id") or item.get("title") or "诊断条目") + "</strong>"
            content += f"<p>{cell(item.get('mechanism') or item.get('description') or item.get('summary') or '')}</p>" + details(item) + "</div>"
        return content

    overview = report["overview"]
    content = ["<p>" + cell(overview["summary"]) + "</p><div class=metrics>" + "".join(
        f"<div><span>{cell(m['label'])}</span><strong>{cell(m['value'])}<small>{cell(m.get('unit', ''))}</small></strong></div>"
        for m in overview["metrics"]) + "</div>"]
    if overview.get("external_summary"):
        content[0] += details(overview["external_summary"], "外部模块的异常概况")
    content[0] += details(overview["observations"], "原始业务可用度观测（不等于异常结论）")
    content += [external(report["causes"]), external(report["watch_items"])]
    routing = report["route_options"]
    states = {"feasible": "找到模型内可行方案", "no_feasible_route": "未找到可行路径", "insufficient_data": "数据不足", "no_change_needed": "无需改路"}
    routes = f"<p><strong>{cell(states.get(routing['status'], routing['status']))}</strong> · {len(routing['proposals'])} 个方案</p>"
    for proposal in routing["proposals"]:
        routes += f"<h3>{cell(proposal['proposal_id'])} · {len(proposal['changes'])} 条业务路径调整</h3>"
        routes += table(["业务", "原路径", "备选路径", "请求量 Mbps", "预计时延 ms"], [
            [c["service_id"], " → ".join(c["before_nodes"]), " → ".join(c["after_nodes"]), c["offered_mbps"], c["estimated_latency_ms"]]
            for c in proposal["changes"]])
        routes += table(["资源", "原预留 Mbps", "新预留 Mbps", "有效容量 Mbps", "预计使用率 %"], [
            [r["object_id"], r["before_reserved_demand_mbps"], r["after_reserved_demand_mbps"], r["capacity_mbps"], r["estimated_demand_utilization_pct"]]
            for r in proposal["resources"]])
    if routing.get("unresolved_risks"):
        routes += details(routing["unresolved_risks"], "仍未解决的其他瓶颈（不属于已修复问题）")
    routes += bullets(routing.get("limitations", []))
    if not routing["proposals"]:
        routes += details(routing, "无方案的约束与缺失数据")
    content += [routes, external(report["impact"]), bullets(report["conclusions"]["items"]) + "<h3>待补证据</h3>" + bullets(report["conclusions"]["missing_evidence"])]
    titles = ["异常概况", "根因候选与异常原因", "潜在或轻微异常", "备选通信路径", "影响与对照", "结论与待补证据"]
    body = "".join(f"<section><h2>{index:02d} {title}</h2>{part}</section>" for index, (title, part) in enumerate(zip(titles, content), 1))
    fixture = " · 外部诊断为开发样例，不是已交付算法结果" if report["provenance"]["diagnosis_is_fixture"] else ""
    source_note = " · 已运行同学诊断模块" if report["provenance"].get("input_source") == "integrated_diagnosis" else (
        " · 已接收外部诊断JSON" if report["provenance"].get("input_source") == "diagnosis_json" else " · 手动待避条件")
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>卫星网络分析与路径建议</title><style>body{font:15px/1.7 system-ui;margin:32px auto;padding:0 20px;max-width:1120px;background:#f4f7fb;color:#19334c}header{border-bottom:4px solid #1268a6;padding-bottom:18px}section{background:white;border:1px solid #dce4ed;border-radius:10px;padding:24px;margin:20px 0}h1,h2{color:#1268a6}h2{font-size:21px;margin-top:0}small{font-size:13px;margin-left:4px}.metrics{display:flex;flex-wrap:wrap;gap:16px}.metrics div{background:#eff5fa;min-width:120px;padding:12px 20px;border-radius:6px}.metrics span,.metrics strong{display:block}.metrics strong{font-size:24px}.table{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px;margin:12px 0}th,td{padding:10px;border-bottom:1px solid #dde6f0;text-align:left}th{background:#edf4fa;white-space:nowrap}td{min-width:80px}details{margin:12px 0}summary{cursor:pointer;color:#1268a6}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.6 ui-monospace,monospace}.item{border-left:3px solid #bdd5ea;padding:10px 16px;margin:12px 0}.notice{color:#8c4c0b}footer{font-size:13px;color:#607487}@media print{body{margin:0;background:white}section{break-inside:auto}details{display:none}}</style></head><body><header><h1>卫星网络分析与路径建议</h1>'
        + f"<p>{cell(report['case_id'])} · 评估时刻 {cell(report['at'])} · 证据截止 {cell(report['as_of'])}</p>"
        + '<p class="notice">模拟数据 · 建议不执行切换 · 候选不代表已确认根因' + cell(source_note) + cell(fixture) + '</p></header>'
        + body + '<footer>完整证据、MCP 查询记录和技术字段请查看同次运行的 JSON 文件与工作台执行记录。</footer></body></html>')


async def _publish(context, spec):
    directory = artifact_root() / context["run_id"]
    directory.mkdir(parents=True, exist_ok=True)
    report = context["report"]
    report["mcp_calls_before_publication"] = list(context["gateway"].calls) if context.get("gateway") else []
    files = [("satellite-report.json", "application/json", json.dumps(report, ensure_ascii=False, indent=2)),
             ("satellite-report.html", "text/html", render_report_html(report))]
    if context.get("diagnosis_raw") is not None:
        files.append(("satellite-diagnosis-raw.json", "application/json",
            json.dumps(context["diagnosis_raw"], ensure_ascii=False, indent=2)))
    context["files"] = []
    for name, mime, content in files:
        target = (directory / name).resolve()
        target.relative_to(artifact_root())
        if target.exists():
            raise ValueError("本次产物已存在，不覆盖旧文件")
        if context["mode"] == "mcp":
            await context["gateway"].call("filesystem", "write_file", {"path": str(target), "content": content})
        else:
            target.write_text(content, encoding="utf-8")
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        context["files"].append({"path": target, "mime": mime, "sha256": digest})
        with session_scope() as session:
            task = session.scalar(select(ExecutionTaskORM).where(ExecutionTaskORM.run_id == context["run_id"], ExecutionTaskORM.task_key == "publish_report"))
            session.add(ArtifactORM(run_id=context["run_id"], task_id=task.id, name=name, kind="satellite_report",
                path=str(target), mime_type=mime, size=target.stat().st_size, artifact_metadata={"sha256": digest, "case_id": report["case_id"], "synthetic": True}))
    return {"files": [{"name": f["path"].name, "sha256": f["sha256"]} for f in context["files"]]}


async def _verify(context, spec):
    for item in context["files"]:
        target = item["path"]
        if context["mode"] == "mcp":
            await context["gateway"].call("filesystem", "get_file_info", {"path": str(target)})
        if not target.is_file() or not target.stat().st_size or hashlib.sha256(target.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("产物校验失败")
    saved = json.loads(context["files"][0]["path"].read_text(encoding="utf-8"))
    if saved != context["report"]:
        raise ValueError("下载报告与本次内存结果不一致")
    return {"passed": True, "file_count": len(context["files"]), "checked": ["exists", "nonempty", "sha256", "report_json_matches"]}


PROCESSORS: dict[str, Callable] = {"satellite.snapshot": _snapshot, "satellite.ontology": _ontology,
    "satellite.diagnosis": _diagnosis, "satellite.diagnosis.auto": _auto_diagnosis,
    "satellite.routing": _routing, "satellite.report": _report,
    "satellite.publish": _publish, "satellite.verify": _verify}


async def _execute(run_id: str):
    with session_scope() as session:
        run = session.get(WorkflowRunORM, run_id)
        if not run or run.workflow_type != "satellite_planning" or run.status != "planning":
            return  # An at-least-once background delivery must not corrupt a terminal run.
        claimed = session.execute(update(WorkflowRunORM).where(WorkflowRunORM.id == run_id,
            WorkflowRunORM.status == "planning").values(status="running", started_at=datetime.now(timezone.utc)))
        if claimed.rowcount != 1:
            return
        contract = dict(run.result_contract)
        tasks = [{"key": task.task_key, "skill_spec": task.skill_spec} for task in session.scalars(select(ExecutionTaskORM)
            .where(ExecutionTaskORM.run_id == run_id).order_by(ExecutionTaskORM.order_index)).all()]
    payload = SatelliteRunCreate.model_validate(contract["request"])
    context = {"run_id": run_id, "contract": contract, "payload": payload, "mode": contract["execution_mode"]}
    completed = set()
    async with AsyncExitStack() as stack:
        if context["mode"] == "mcp":
            config = mcp_config()
            context["gateway"] = await stack.enter_async_context(McpGateway(config.get("servers", {})))
        for index, task in enumerate(tasks):
            key, spec = task["key"], task["skill_spec"]
            before = len(context["gateway"].calls) if context.get("gateway") else 0
            _task_state(run_id, key, "running")
            try:
                processor = spec.get("processor")
                if processor not in PROCESSORS or not set(spec.get("depends_on", [])) <= completed:
                    raise ValueError("处理器未注册或依赖尚未完成")
                evidence = await PROCESSORS[processor](context, spec)
                calls = context["gateway"].calls[before:] if context.get("gateway") else []
                evidence.update(mcp_calls=calls, processor=processor, ontology_rule=spec.get("ontology_rule"), execution_mode=context["mode"])
                _task_state(run_id, key, "succeeded", evidence=evidence, outputs=list(evidence.get("files", [])))
                completed.add(key)
                with session_scope() as session:
                    run = session.get(WorkflowRunORM, run_id)
                    summary = dict(run.summary)
                    summary.update(progress=round((index + 1) / len(tasks) * 100), completed_tasks=index + 1)
                    if context.get("report"):
                        summary["satellite_report"] = context["report"]
                        summary["diagnosis_status"] = context["report"]["diagnosis_status"]
                    if context.get("gateway"): summary["mcp_call_count"] = len(context["gateway"].calls)
                    run.summary = summary
            except BaseException as exc:
                calls = context["gateway"].calls[before:] if context.get("gateway") else []
                _task_state(run_id, key, "failed", evidence={"mcp_calls": calls, "processor": spec.get("processor")}, error=describe_exception(exc))
                raise
    with session_scope() as session:
        run = session.get(WorkflowRunORM, run_id)
        run.status, run.completed_at = "succeeded", datetime.now(timezone.utc)


def execute_satellite_run(run_id: str):
    try:
        asyncio.run(_execute(run_id))
    except BaseException as exc:
        with session_scope() as session:
            run = session.get(WorkflowRunORM, run_id)
            if run and run.workflow_type == "satellite_planning" and run.status == "running":
                run.status, run.error, run.completed_at = "failed", describe_exception(exc), datetime.now(timezone.utc)
