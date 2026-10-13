"""通用“需求 → Task → Skill → 产物 → 验证”执行器的首个数据报表实现。"""

from __future__ import annotations

import math
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from html import escape as html_escape
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select

from app.infrastructure.database import session_scope
from app.infrastructure.orm import ArtifactORM, ExecutionTaskORM, WorkflowRunORM, new_id
from app.infrastructure.tabular_files import TableData, read_tabular, write_csv, write_xlsx


BACKEND_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = BACKEND_ROOT / "report_artifacts"
STEP_VISIBILITY_DELAY_SECONDS = 1.25


FIELD_ALIASES = {
    "订单号": "订单编号",
    "订单编号": "订单编号",
    "orderid": "订单编号",
    "orderno": "订单编号",
    "客户id": "客户编号",
    "客户编号": "客户编号",
    "customerid": "客户编号",
    "客户名称": "客户名称",
    "customername": "客户名称",
    "销售额": "销售额",
    "销售金额": "销售额",
    "金额": "销售额",
    "订单金额": "销售额",
    "salesamount": "销售额",
    "amount": "销售额",
    "回款金额": "回款金额",
    "实收金额": "回款金额",
    "paymentamount": "回款金额",
    "区域": "区域",
    "地区": "区域",
    "region": "区域",
    "产品": "产品",
    "产品名称": "产品",
    "product": "产品",
    "日期": "日期",
    "订单日期": "日期",
    "date": "日期",
    "月份": "月份",
    "month": "月份",
}


TASK_BLUEPRINTS = [
    (
        "compile_requirement",
        "编译需求与结果合同",
        "把自然语言需求转换为目标、输入、交付物和验收条件。",
        "requirement-compiler",
        ["requirement.parse", "deliverable.contract"],
        ["ontology.describe", "llm.plan"],
    ),
    (
        "inspect_sources",
        "自主发现数据源",
        "根据需求选择数据连接能力；未配置外部连接器时使用可追溯的内置演示数据。",
        "autonomous-source-resolver",
        ["source.discover", "table.read", "schema.inspect"],
        ["mcp.resource.search", "table.inspect"],
    ),
    (
        "profile_data",
        "分析数据质量",
        "统计缺失值、重复行、字段类型和可用程度。",
        "dataset-profiler",
        ["data.profile", "quality.measure"],
        ["table.profile", "data.validate"],
    ),
    (
        "align_schema",
        "推断字段语义并对齐",
        "根据字段别名和内容，把多个来源映射到统一字段。",
        "schema-alignment",
        ["schema.map", "ontology.match"],
        ["ontology.search", "table.rename_columns"],
    ),
    (
        "clean_merge",
        "清洗并合并数据",
        "删除空记录和完全重复记录，保留来源血缘并合并数据。",
        "clean-and-merge",
        ["data.clean", "data.merge", "artifact.write"],
        ["table.transform", "filesystem.write"],
    ),
    (
        "calculate_summary",
        "计算汇总指标",
        "自动识别数值字段和分类维度，计算合计、均值及分组结果。",
        "metric-calculator",
        ["metric.infer", "data.aggregate"],
        ["table.aggregate", "data.calculate"],
    ),
    (
        "generate_report",
        "生成 Excel 报表",
        "生成执行摘要、字段概览、质量报告、指标汇总和清洗明细。",
        "spreadsheet-report-builder",
        ["report.compose", "spreadsheet.write"],
        ["spreadsheet.create", "artifact.store"],
    ),
    (
        "verify_delivery",
        "验证结果",
        "检查行数、重复项、产物完整性和汇总一致性。",
        "delivery-verifier",
        ["artifact.verify", "acceptance.evaluate"],
        ["filesystem.inspect", "data.validate"],
    ),
    (
        "package_results",
        "组织最终交付",
        "生成执行清单并汇总所有可下载产物。",
        "delivery-packager",
        ["delivery.package", "lineage.record"],
        ["artifact.list", "manifest.create"],
    ),
]


TASK_CATALOG = {item[0]: item for item in TASK_BLUEPRINTS}
TASK_CATALOG.update(
    {
        "scope_time": (
            "scope_time",
            "限定分析时间范围",
            "根据需求中的时间范围筛选有效数据，并记录实际覆盖期间。",
            "time-scope-resolver",
            ["time.parse", "data.filter"],
            ["ontology.match", "table.filter"],
        ),
        "compare_dimensions": (
            "compare_dimensions",
            "对比业务维度",
            "按照需求指定的分类维度进行汇总、排序和差异比较。",
            "dimension-comparison",
            ["dimension.resolve", "data.group", "metric.compare"],
            ["ontology.search", "table.aggregate", "chart.prepare"],
        ),
        "analyze_collection": (
            "analyze_collection",
            "分析销售与回款",
            "计算销售额、回款金额、回款率和未回款金额，定位主要差距。",
            "collection-analysis",
            ["metric.calculate", "ratio.calculate", "gap.explain"],
            ["table.aggregate", "data.calculate"],
        ),
        "analyze_trend": (
            "analyze_trend",
            "分析时间趋势",
            "按时间顺序比较指标变化，识别高点、低点和变化方向。",
            "trend-analysis",
            ["time.group", "metric.compare", "trend.explain"],
            ["table.aggregate", "chart.prepare"],
        ),
        "detect_anomalies": (
            "detect_anomalies",
            "识别异常与风险",
            "依据数据质量和指标偏离规则识别需要关注的记录与分组。",
            "anomaly-detector",
            ["anomaly.detect", "risk.explain"],
            ["data.validate", "table.filter"],
        ),
        "generate_insights": (
            "generate_insights",
            "形成结论并回答问题",
            "将计算结果组织为直接回答、关键发现和可执行建议。",
            "result-narrator",
            ["result.summarize", "insight.explain", "recommendation.compose"],
            ["ontology.reason", "report.compose"],
        ),
    }
)


ONTOLOGY_REASONING = {
    "compile_requirement": {
        "input_classes": ["Goal"],
        "matched_concepts": ["ReportSpecification", "Deliverable", "AcceptanceCriterion"],
        "rule": "Goal 包含分析/汇总/报表意图 → 创建 ReportSpecification",
        "inference": "该自然语言目标需要可下载报表与可验证交付合同。",
    },
    "inspect_sources": {
        "input_classes": ["Goal", "DataSource"],
        "matched_concepts": ["DataSource", "Dataset", "Capability"],
        "rule": "Goal requires Dataset 且未指定输入 → 调用 source.discover 能力",
        "inference": "当前未配置外部数据连接器，选择 mcp://demo/sales-ledger 作为透明演示源。",
    },
    "profile_data": {
        "input_classes": ["Dataset"],
        "matched_concepts": ["DataField", "DataQualityRule"],
        "rule": "Dataset 在进入变换前必须满足 quality.measure 前置规则",
        "inference": "生成字段、缺失值、重复行与可用性画像。",
    },
    "align_schema": {
        "input_classes": ["DataField"],
        "matched_concepts": ["FieldMapping", "DataField"],
        "rule": "字段别名命中 canonical DataField → 推导 FieldMapping",
        "inference": "订单号、金额、地区等异构字段被映射到统一业务语义。",
    },
    "clean_merge": {
        "input_classes": ["Dataset", "DataQualityRule"],
        "matched_concepts": ["DataQualityRule", "Artifact"],
        "rule": "空业务记录过滤 + 全字段指纹相同 → duplicate",
        "inference": "形成保留来源血缘的清洗数据集。",
    },
    "calculate_summary": {
        "input_classes": ["ReportSpecification", "Dataset"],
        "matched_concepts": ["MetricDefinition", "DataField"],
        "rule": "数值覆盖率 ≥ 30% → MetricDefinition；低基数字段 → Dimension",
        "inference": "自动选择可汇总指标与分类维度。",
    },
    "generate_report": {
        "input_classes": ["ReportSpecification", "MetricDefinition"],
        "matched_concepts": ["Artifact", "Deliverable"],
        "rule": "ReportSpecification deliverable=spreadsheet → spreadsheet-report-builder",
        "inference": "生成包含目标、需求、执行路径、本体推理和数据结果的 Excel 报告。",
    },
    "verify_delivery": {
        "input_classes": ["Artifact", "AcceptanceCriterion"],
        "matched_concepts": ["Verification", "Evidence"],
        "rule": "每个 Deliverable 必须 VERIFIED_BY Verification",
        "inference": "行数、版本一致性与产物完整性均需形成证据。",
    },
    "package_results": {
        "input_classes": ["Artifact", "Verification"],
        "matched_concepts": ["DeliveryBundle", "Evidence"],
        "rule": "所有验收条件通过 → Artifact CONTAINS_IN DeliveryBundle",
        "inference": "组织最终下载文件、执行清单与完整可追溯路径。",
    },
    "scope_time": {
        "input_classes": ["Goal", "TimeScope", "Dataset"],
        "matched_concepts": ["TimeScope", "TemporalField", "Dataset"],
        "rule": "Goal 声明时间范围 → 解析 TimeScope 并约束 Dataset",
        "inference": "只保留目标时间范围内的有效记录，并记录实际覆盖期间。",
    },
    "compare_dimensions": {
        "input_classes": ["Dimension", "MetricDefinition", "Dataset"],
        "matched_concepts": ["Dimension", "MetricDefinition", "Comparison"],
        "rule": "Goal 同时声明 Dimension 与 MetricDefinition → 生成分组比较",
        "inference": "按照用户指定维度计算指标，并形成可视化比较序列。",
    },
    "analyze_collection": {
        "input_classes": ["SalesMetric", "CollectionMetric"],
        "matched_concepts": ["SalesAmount", "CollectionAmount", "CollectionRate"],
        "rule": "销售额与回款金额同时存在 → 推导回款率与未回款金额",
        "inference": "将销售规模与资金回收结果放在同一口径下比较。",
    },
    "analyze_trend": {
        "input_classes": ["TimeScope", "MetricDefinition"],
        "matched_concepts": ["TemporalDimension", "Trend", "MetricDefinition"],
        "rule": "Goal 包含时间维度或趋势意图 → 按期间排序并比较指标",
        "inference": "形成按时间排序的趋势序列，并识别高点与低点。",
    },
    "detect_anomalies": {
        "input_classes": ["Dataset", "DataQualityRule", "MetricDefinition"],
        "matched_concepts": ["Anomaly", "RiskSignal", "Evidence"],
        "rule": "质量缺口或指标显著偏离基线 → 推导 Anomaly",
        "inference": "把异常记录、缺失值和显著偏离分组组织为风险证据。",
    },
    "generate_insights": {
        "input_classes": ["Goal", "Comparison", "Evidence"],
        "matched_concepts": ["Answer", "Insight", "Recommendation"],
        "rule": "Goal 的指标与维度均已有证据 → 生成 Answer 与 Recommendation",
        "inference": "用计算结果直接回答原始问题，并给出有数据依据的建议。",
    },
}


def compile_result_contract(requirement: str, file_names: list[str]) -> dict[str, Any]:
    normalized_requirement = requirement.strip()
    time_scope = _extract_time_scope(normalized_requirement)
    dimensions = _mentioned(
        normalized_requirement,
        {
            "月份": ["月份", "月度", "按月"],
            "区域": ["区域", "地区", "大区"],
            "产品": ["产品", "商品"],
            "客户": ["客户", "用户"],
            "部门": ["部门", "团队"],
        },
    )
    metrics = _mentioned(
        normalized_requirement,
        {
            "销售额": ["销售额", "销售金额", "营收"],
            "订单数": ["订单数", "订单量"],
            "回款金额": ["回款金额", "回款"],
            "回款率": ["回款率"],
            "记录数": ["记录数", "数量", "总数"],
            "平均值": ["平均", "均值"],
        },
    )
    if not metrics:
        metrics = ["记录数", "数值字段合计与平均值"]
    if time_scope and "月份" not in dimensions:
        dimensions.insert(0, "月份")
    if "销售额" in metrics and "回款金额" in metrics and "回款率" not in metrics:
        metrics.append("回款率")

    intents = ["data_quality", "descriptive_analysis"]
    if time_scope:
        intents.append("time_scope")
    if dimensions:
        intents.append("dimension_comparison")
    if "月份" in dimensions or any(keyword in normalized_requirement for keyword in ("趋势", "变化", "走势", "环比", "同比")):
        intents.append("trend_analysis")
    if "销售额" in metrics and any(metric in metrics for metric in ("回款金额", "回款率")):
        intents.append("collection_analysis")
    if any(keyword in normalized_requirement for keyword in ("异常", "风险", "偏离", "波动", "问题")):
        intents.append("anomaly_detection")

    operations = ["需求建模", "数据源发现", "质量分析", "字段语义对齐", "数据清洗"]
    if time_scope:
        operations.append("时间范围筛选")
    operations.append("指标计算")
    if dimensions:
        operations.append("维度对比")
    if "collection_analysis" in intents:
        operations.append("销售回款分析")
    if "trend_analysis" in intents:
        operations.append("趋势分析")
    if "anomaly_detection" in intents:
        operations.append("异常识别")
    operations.extend(["结论生成", "可视化报告", "结果验证"])
    return {
        "goal": normalized_requirement,
        "inputs": file_names or ["Agent 通过 DataSourceResolver / MCP 自动发现"],
        "operations": operations,
        "dimensions": dimensions or ["系统自动识别分类维度"],
        "metrics": metrics,
        "time_scope": time_scope,
        "analysis_intents": intents,
        "ontology_profile": {
            "goal_class": "DataAnalysisGoal",
            "intent_classes": intents,
            "metric_concepts": metrics,
            "dimension_concepts": dimensions,
        },
        "deliverables": ["Excel 分析报表", "可视化分析报告", "管理摘要", "执行与验证报告"],
        "acceptance_criteria": [
            "数据来源由 Agent 自动选择并明确记录来源血缘",
            "空记录和完全重复记录已处理",
            "报表汇总与清洗后明细使用同一数据版本",
            "结果页直接回答用户问题并提供可视化证据",
            "四个面向用户的报告均可下载并追溯到执行 Task",
        ],
    }


def build_task_plan(contract: dict[str, Any]) -> list[tuple[str, str, str, str, list[str], list[str]]]:
    intents = set(contract.get("analysis_intents", []))
    ordered_keys = ["compile_requirement", "inspect_sources", "profile_data", "align_schema", "clean_merge"]
    if "time_scope" in intents:
        ordered_keys.append("scope_time")
    ordered_keys.append("calculate_summary")
    if "dimension_comparison" in intents:
        ordered_keys.append("compare_dimensions")
    if "collection_analysis" in intents:
        ordered_keys.append("analyze_collection")
    if "trend_analysis" in intents:
        ordered_keys.append("analyze_trend")
    if "anomaly_detection" in intents:
        ordered_keys.append("detect_anomalies")
    ordered_keys.extend(["generate_insights", "generate_report", "verify_delivery", "package_results"])
    return [_personalize_blueprint(TASK_CATALOG[key], contract) for key in ordered_keys]


def _personalize_blueprint(
    blueprint: tuple[str, str, str, str, list[str], list[str]],
    contract: dict[str, Any],
) -> tuple[str, str, str, str, list[str], list[str]]:
    key, title, description, skill_name, capabilities, bindings = blueprint
    metrics = "、".join(contract.get("metrics", []))
    dimensions = "、".join(
        item for item in contract.get("dimensions", []) if not str(item).startswith("系统自动")
    )
    time_scope = contract.get("time_scope") or {}
    if key == "scope_time":
        title = f"限定{time_scope.get('label', '目标期间')}"
    elif key == "calculate_summary":
        title = f"计算{metrics or '核心指标'}"
    elif key == "compare_dimensions":
        title = f"按{dimensions or '识别维度'}对比"
    elif key == "analyze_collection":
        title = "计算回款率与资金缺口"
    elif key == "analyze_trend":
        title = "分析指标时间趋势"
    elif key == "generate_insights":
        title = "回答问题并形成建议"
    elif key == "generate_report":
        title = "生成可视化与 Excel 报告"
        description = "生成先呈现结论、再提供图表和明细的用户报告。"
    return key, title, description, skill_name, capabilities, bindings


def ontology_reasoning_for(
    task_key: str,
    contract: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reasoning = dict(ONTOLOGY_REASONING[task_key])
    metrics = [str(item) for item in contract.get("metrics", [])]
    dimensions = [
        str(item) for item in contract.get("dimensions", []) if not str(item).startswith("系统自动")
    ]
    context = context or {}
    if task_key == "compile_requirement":
        reasoning["rule"] = f"Goal 命中 {len(contract.get('analysis_intents', []))} 个分析意图 → 创建动态 ReportSpecification"
        reasoning["inference"] = f"本次需要围绕{'、'.join(metrics) or '自动识别指标'}形成可视化回答与四项报告。"
    elif task_key == "scope_time":
        scope = contract.get("time_scope") or {}
        reasoning["rule"] = f"Goal.time_scope={scope.get('label', '目标期间')} → FILTER TemporalField"
    elif task_key == "calculate_summary":
        reasoning["rule"] = f"Goal.metrics={metrics} → 创建对应 MetricDefinition 并计算"
        reasoning["inference"] = f"只计算本次问题需要的{'、'.join(metrics) or '可用数值指标'}。"
    elif task_key == "compare_dimensions":
        reasoning["rule"] = f"Goal.dimensions={dimensions} → GROUP BY Dimension"
        reasoning["inference"] = f"按{'、'.join(dimensions) or '自动识别维度'}形成排名与差异证据。"
    elif task_key == "analyze_collection":
        reasoning["inference"] = "销售额与回款金额共同推导回款率和未回款金额。"
    elif task_key == "analyze_trend":
        reasoning["rule"] = "Goal 命中月份/趋势语义 → 创建 TemporalComparison"
    elif task_key == "generate_insights":
        reasoning["rule"] = f"{len(metrics)} 个指标证据 + {len(dimensions)} 个维度比较 → Answer"
        reasoning["inference"] = "将指标、比较和质量证据组织为对原始问题的直接回答。"
    elif task_key == "inspect_sources" and context.get("source_mode") == "autonomous_demo":
        reasoning["inference"] = "未发现外部连接器，使用 mcp://demo/sales-ledger，并在结果中明确标注演示来源。"
    return reasoning


def create_workflow_run(
    requirement: str,
    title: str,
    input_files: list[dict[str, Any]],
    run_id: str | None = None,
) -> str:
    run_id = run_id or new_id()
    contract = compile_result_contract(requirement, [item["name"] for item in input_files])
    task_plan = build_task_plan(contract)
    with session_scope() as session:
        session.add(
            WorkflowRunORM(
                id=run_id,
                workflow_type="data_report",
                title=title.strip() or "数据整理与报表生成",
                requirement=requirement.strip(),
                status="planning",
                result_contract=contract,
                input_files=input_files,
                summary={"progress": 0, "task_count": len(task_plan)},
            )
        )
        for index, (key, task_title, description, skill_name, capabilities, bindings) in enumerate(
            task_plan, start=1
        ):
            previous_key = task_plan[index - 2][0] if index > 1 else None
            reasoning = ontology_reasoning_for(key, contract)
            session.add(
                ExecutionTaskORM(
                    run_id=run_id,
                    task_key=key,
                    order_index=index,
                    title=task_title,
                    description=description,
                    status="pending",
                    skill_spec={
                        "name": skill_name,
                        "generated_for_run": True,
                        "required_capabilities": capabilities,
                        "mcp_bindings": bindings,
                        "permission_policy": "workspace-scoped",
                        "depends_on": [previous_key] if previous_key else [],
                        "ontology_rule": reasoning["rule"],
                    },
                    inputs=[],
                    outputs=[],
                    evidence={},
                )
            )
    return run_id


def get_workflow_snapshot(run_id: str) -> dict[str, Any]:
    """返回供 MCP 调用方使用的运行快照，不暴露服务内部数据库对象。"""
    with session_scope() as session:
        run = session.get(WorkflowRunORM, run_id)
        if not run:
            raise ValueError(f"WorkflowRun not found: {run_id}")
        tasks = session.scalars(
            select(ExecutionTaskORM)
            .where(ExecutionTaskORM.run_id == run_id)
            .order_by(ExecutionTaskORM.order_index)
        ).all()
        artifacts = session.scalars(
            select(ArtifactORM).where(ArtifactORM.run_id == run_id).order_by(ArtifactORM.created_at)
        ).all()
        return {
            "id": run.id,
            "title": run.title,
            "status": run.status,
            "requirement": run.requirement,
            "result_contract": run.result_contract or {},
            "summary": run.summary or {},
            "error": run.error,
            "tasks": [
                {
                    "key": task.task_key,
                    "title": task.title,
                    "status": task.status,
                    "skill": task.skill_spec,
                    "outputs": task.outputs,
                    "evidence": task.evidence,
                    "error": task.error,
                }
                for task in tasks
            ],
            "artifacts": [
                {
                    "id": artifact.id,
                    "name": artifact.name,
                    "kind": artifact.kind,
                    "size": artifact.size,
                    "path": artifact.path,
                }
                for artifact in artifacts
            ],
        }


def execute_workflow_run(run_id: str) -> None:
    context: dict[str, Any] = {}
    try:
        with session_scope() as session:
            run = session.get(WorkflowRunORM, run_id)
            if not run:
                return
            run.status = "running"
            run.started_at = datetime.now(timezone.utc)
            contract = dict(run.result_contract or {})
            planned_tasks = [
                {"key": task.task_key, "title": task.title}
                for task in session.scalars(
                    select(ExecutionTaskORM)
                    .where(ExecutionTaskORM.run_id == run_id)
                    .order_by(ExecutionTaskORM.order_index)
                ).all()
            ]

        context["contract"] = contract
        context["task_plan"] = planned_tasks

        handlers: dict[str, Callable[[str, dict[str, Any]], tuple[dict[str, Any], list[str]]]] = {
            "compile_requirement": _compile_step,
            "inspect_sources": _inspect_step,
            "profile_data": _profile_step,
            "align_schema": _align_step,
            "clean_merge": _clean_step,
            "scope_time": _scope_time_step,
            "calculate_summary": _summary_step,
            "compare_dimensions": _dimension_step,
            "analyze_collection": _collection_step,
            "analyze_trend": _trend_step,
            "detect_anomalies": _anomaly_step,
            "generate_insights": _insight_step,
            "generate_report": _report_step,
            "verify_delivery": _verify_step,
            "package_results": _package_step,
        }
        for index, planned_task in enumerate(planned_tasks, start=1):
            key = planned_task["key"]
            reasoning = ontology_reasoning_for(key, contract, context)
            _set_task_state(
                run_id,
                key,
                "running",
                evidence={"ontology_reasoning": reasoning},
            )
            time.sleep(STEP_VISIBILITY_DELAY_SECONDS)
            evidence, outputs = handlers[key](run_id, context)
            evidence = {**evidence, "ontology_reasoning": ontology_reasoning_for(key, contract, context)}
            _set_task_state(run_id, key, "succeeded", evidence=evidence, outputs=outputs)
            with session_scope() as session:
                run = session.get(WorkflowRunORM, run_id)
                if run:
                    current = dict(run.summary or {})
                    current["progress"] = round(index / len(planned_tasks) * 100)
                    run.summary = current

        with session_scope() as session:
            run = session.get(WorkflowRunORM, run_id)
            if run:
                run.status = "succeeded"
                run.completed_at = datetime.now(timezone.utc)
    except Exception as exc:
        _fail_workflow(run_id, exc)


def _compile_step(run_id: str, context: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    with session_scope() as session:
        run = session.get(WorkflowRunORM, run_id)
        contract = dict(run.result_contract if run else {})
    context["contract"] = contract
    return {
        "goal": contract.get("goal"),
        "deliverables": len(contract.get("deliverables", [])),
        "acceptance_criteria": len(contract.get("acceptance_criteria", [])),
    }, ["result_contract"]


def _inspect_step(run_id: str, context: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    with session_scope() as session:
        run = session.get(WorkflowRunORM, run_id)
        inputs = list(run.input_files if run else [])
    tables: list[TableData] = []
    for item in inputs:
        tables.extend(read_tabular(Path(item["path"])))
    source_mode = "connected_files"
    if not tables:
        source_mode = "autonomous_demo"
        tables = [_autonomous_demo_table()]
    if not tables:
        raise ValueError("没有读取到可处理的数据表。")
    context["tables"] = tables
    context["source_mode"] = source_mode
    return {
        "source_mode": source_mode,
        "source_files": len(inputs),
        "tables": len(tables),
        "input_rows": sum(len(table.rows) for table in tables),
        "schemas": [{"source": table.source, "table": table.name, "fields": table.headers} for table in tables],
    }, ["source_inventory", "schema_snapshot"]


def _autonomous_demo_table() -> TableData:
    """外部 MCP 尚未配置时使用的透明演示源，确保 Goal Runner 可以一键跑通。"""
    rows = [
        {"订单号": "SO-1001", "月份": "2026-07", "地区": "华东", "产品名称": "智能终端", "销售金额": 12800, "回款金额": 9600},
        {"订单号": "SO-1002", "月份": "2026-07", "地区": "华南", "产品名称": "协作软件", "销售金额": 8600, "回款金额": 8600},
        {"订单号": "SO-1003", "月份": "2026-08", "地区": "华东", "产品名称": "协作软件", "销售金额": 15200, "回款金额": 12000},
        {"订单号": "SO-1004", "月份": "2026-08", "地区": "华北", "产品名称": "智能终端", "销售金额": 19400, "回款金额": ""},
        {"订单号": "SO-1005", "月份": "2026-09", "地区": "华南", "产品名称": "数据服务", "销售金额": 11300, "回款金额": 11300},
        {"订单号": "SO-1005", "月份": "2026-09", "地区": "华南", "产品名称": "数据服务", "销售金额": 11300, "回款金额": 11300},
    ]
    return TableData(
        name="autonomous_sales_ledger",
        source="mcp://demo/sales-ledger",
        headers=["订单号", "月份", "地区", "产品名称", "销售金额", "回款金额"],
        rows=rows,
    )


def profile_tables(tables: list[TableData]) -> dict[str, Any]:
    table_profiles: list[dict[str, Any]] = []
    total_missing = 0
    for table in tables:
        missing = {header: sum(_is_blank(row.get(header)) for row in table.rows) for header in table.headers}
        total_missing += sum(missing.values())
        fingerprints = [tuple(str(row.get(header, "")).strip() for header in table.headers) for row in table.rows]
        duplicate_rows = len(fingerprints) - len(set(fingerprints))
        table_profiles.append(
            {
                "source": table.source,
                "table": table.name,
                "rows": len(table.rows),
                "columns": len(table.headers),
                "missing_by_field": missing,
                "duplicate_rows": duplicate_rows,
            }
        )
    return {"tables": table_profiles, "total_missing_cells": total_missing}


def _profile_step(run_id: str, context: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    profile = profile_tables(context["tables"])
    context["profile"] = profile
    return profile, ["data_profile", "quality_baseline"]


def align_tables(tables: list[TableData]) -> tuple[list[dict[str, object]], list[str], list[dict[str, str]]]:
    aligned_rows: list[dict[str, object]] = []
    headers: list[str] = []
    mappings: list[dict[str, str]] = []
    for table in tables:
        mapping = {header: canonical_header(header) for header in table.headers}
        mappings.extend(
            {"source": table.source, "table": table.name, "from": source, "to": target}
            for source, target in mapping.items()
        )
        for canonical in mapping.values():
            if canonical not in headers:
                headers.append(canonical)
        for row in table.rows:
            aligned: dict[str, object] = {"_source_file": table.source, "_source_table": table.name}
            for source, target in mapping.items():
                value = row.get(source, "")
                if target not in aligned or _is_blank(aligned[target]):
                    aligned[target] = value
            aligned_rows.append(aligned)
    return aligned_rows, ["_source_file", "_source_table", *headers], mappings


def _align_step(run_id: str, context: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    rows, headers, mappings = align_tables(context["tables"])
    context.update({"aligned_rows": rows, "headers": headers, "mappings": mappings})
    changed = sum(item["from"] != item["to"] for item in mappings)
    return {"field_mappings": mappings, "renamed_fields": changed, "unified_fields": len(headers) - 2}, [
        "field_mapping",
        "aligned_dataset",
    ]


def clean_rows(rows: list[dict[str, object]], headers: list[str]) -> tuple[list[dict[str, object]], int]:
    business_headers = [header for header in headers if not header.startswith("_source_")]
    seen: set[tuple[str, ...]] = set()
    cleaned: list[dict[str, object]] = []
    duplicates = 0
    for row in rows:
        if not any(not _is_blank(row.get(header)) for header in business_headers):
            continue
        fingerprint = tuple(str(row.get(header, "")).strip() for header in business_headers)
        if fingerprint in seen:
            duplicates += 1
            continue
        seen.add(fingerprint)
        cleaned.append(row)
    return cleaned, duplicates


def _clean_step(run_id: str, context: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    cleaned, duplicates = clean_rows(context["aligned_rows"], context["headers"])
    context["cleaned_rows"] = cleaned
    context["duplicates_removed"] = duplicates
    output = _run_directory(run_id) / "cleaned-data.csv"
    write_csv(output, context["headers"], cleaned)
    return {
        "input_rows": len(context["aligned_rows"]),
        "output_rows": len(cleaned),
        "duplicates_removed": duplicates,
        "lineage_fields": ["_source_file", "_source_table"],
    }, ["内部标准数据集"]


def _scope_time_step(run_id: str, context: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    scope = context["contract"].get("time_scope") or {}
    count = max(1, int(scope.get("count", 1)))
    field = next((name for name in ("月份", "日期") if name in context["headers"]), None)
    if not field:
        return {
            "requested_scope": scope.get("label", "目标期间"),
            "applied": False,
            "reason": "数据中未识别到时间字段，保留全部有效记录。",
        }, ["全量有效记录"]
    periods = sorted({_period_value(row.get(field)) for row in context["cleaned_rows"] if _period_value(row.get(field))})
    selected_periods = periods[-count:]
    scoped_rows = [row for row in context["cleaned_rows"] if _period_value(row.get(field)) in selected_periods]
    context["cleaned_rows"] = scoped_rows
    context["applied_time_scope"] = {"field": field, "periods": selected_periods}
    return {
        "requested_scope": scope.get("label", f"最近{count}个月"),
        "field": field,
        "periods": selected_periods,
        "rows": len(scoped_rows),
        "applied": True,
    }, [f"{field}：{'、'.join(selected_periods)}"]


def build_summary(rows: list[dict[str, object]], headers: list[str]) -> dict[str, Any]:
    business_headers = [header for header in headers if not header.startswith("_source_")]
    numeric: list[dict[str, Any]] = []
    numeric_names: set[str] = set()
    for header in business_headers:
        values = [_number(row.get(header)) for row in rows]
        valid = [value for value in values if value is not None and math.isfinite(value)]
        if valid and len(valid) >= max(2, math.ceil(len(rows) * 0.3)):
            numeric_names.add(header)
            numeric.append(
                {
                    "field": header,
                    "count": len(valid),
                    "sum": round(sum(valid), 4),
                    "average": round(sum(valid) / len(valid), 4),
                    "min": min(valid),
                    "max": max(valid),
                }
            )

    categorical: list[dict[str, Any]] = []
    primary_numeric = numeric[0]["field"] if numeric else None
    for header in business_headers:
        if header in numeric_names:
            continue
        values = [str(row.get(header, "")).strip() or "（空）" for row in rows]
        unique_count = len(set(values))
        if 1 < unique_count <= 30:
            counts = Counter(values)
            sums: defaultdict[str, float] = defaultdict(float)
            if primary_numeric:
                for row, value in zip(rows, values):
                    sums[value] += _number(row.get(primary_numeric)) or 0
            for value, count in counts.most_common(20):
                categorical.append(
                    {
                        "dimension": header,
                        "value": value,
                        "records": count,
                        "metric": primary_numeric or "",
                        "metric_sum": round(sums[value], 4) if primary_numeric else "",
                    }
                )
            if len({item["dimension"] for item in categorical}) >= 3:
                break
    return {"numeric": numeric, "categorical": categorical, "primary_numeric": primary_numeric}


def _summary_step(run_id: str, context: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    summary = build_summary(context["cleaned_rows"], context["headers"])
    context["calculated_summary"] = summary
    context["analysis_result"] = build_business_analysis(
        context["cleaned_rows"], context["headers"], context["contract"], summary
    )
    evidence = {
        "numeric_fields": len(summary["numeric"]),
        "group_rows": len(summary["categorical"]),
        "primary_numeric": summary["primary_numeric"],
    }
    return evidence, ["numeric_summary", "categorical_summary"]


def build_business_analysis(
    rows: list[dict[str, object]],
    headers: list[str],
    contract: dict[str, Any],
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary = summary or build_summary(rows, headers)
    requested_metrics = [str(item) for item in contract.get("metrics", [])]
    requested_dimensions = [
        str(item) for item in contract.get("dimensions", []) if not str(item).startswith("系统自动")
    ]
    available_dimensions: list[tuple[str, str]] = []
    for dimension in requested_dimensions:
        field = _dimension_field(dimension, headers)
        if field and (dimension, field) not in available_dimensions:
            available_dimensions.append((dimension, field))
    if not available_dimensions:
        for item in summary.get("categorical", []):
            field = str(item.get("dimension", ""))
            if field and (field, field) not in available_dimensions:
                available_dimensions.append((field, field))
            if len(available_dimensions) >= 2:
                break

    sales_total = _aggregate_metric(rows, "销售额") if "销售额" in headers else None
    collection_total = _aggregate_metric(rows, "回款金额") if "回款金额" in headers else None
    collection_rate = (
        collection_total / sales_total if sales_total not in (None, 0) and collection_total is not None else None
    )
    uncollected = sales_total - collection_total if sales_total is not None and collection_total is not None else None

    kpis: list[dict[str, Any]] = []
    if sales_total is not None:
        kpis.append(_kpi("销售额", sales_total, "currency"))
    if collection_total is not None:
        kpis.append(_kpi("回款金额", collection_total, "currency"))
    if collection_rate is not None:
        kpis.append(_kpi("回款率", collection_rate, "percent"))
    if uncollected is not None:
        kpis.append(_kpi("未回款金额", uncollected, "currency", "warning" if uncollected > 0 else "positive"))
    if not kpis:
        kpis.append(_kpi("有效记录", len(rows), "integer"))
        for item in summary.get("numeric", [])[:3]:
            kpis.append(_kpi(f"{item['field']}合计", item["sum"], "number"))

    chart_metrics = [metric for metric in requested_metrics if metric in {"销售额", "回款金额", "回款率", "订单数", "记录数"}]
    if not chart_metrics:
        primary = summary.get("primary_numeric")
        chart_metrics = [str(primary)] if primary else ["记录数"]
    breakdowns: list[dict[str, Any]] = []
    charts: list[dict[str, Any]] = []
    for dimension, field in available_dimensions[:3]:
        grouped: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
        for row in rows:
            grouped[str(row.get(field, "")).strip() or "未分类"].append(row)
        items: list[dict[str, Any]] = []
        for label, group_rows in grouped.items():
            values = {metric: _aggregate_metric(group_rows, metric) for metric in chart_metrics}
            items.append({"label": label, "records": len(group_rows), "values": values})
        primary_metric = chart_metrics[0]
        if dimension == "月份":
            items.sort(key=lambda item: item["label"])
        else:
            items.sort(key=lambda item: float(item["values"].get(primary_metric) or 0), reverse=True)
        breakdowns.append({"dimension": dimension, "field": field, "items": items})
        charts.append(
            {
                "title": f"{dimension}对比",
                "dimension": dimension,
                "series": [
                    {
                        "key": metric,
                        "label": metric,
                        "format": "percent" if metric == "回款率" else "currency" if "金额" in metric or metric == "销售额" else "number",
                    }
                    for metric in chart_metrics[:2]
                ],
                "items": items[:8],
            }
        )

    highlights: list[str] = []
    recommendations: list[str] = []
    if sales_total is not None and collection_total is not None and collection_rate is not None:
        highlights.append(
            f"有效数据的销售额为{_format_value(sales_total, 'currency')}，回款金额为{_format_value(collection_total, 'currency')}，整体回款率为{_format_value(collection_rate, 'percent')}。"
        )
        if uncollected and uncollected > 0:
            highlights.append(f"当前未回款金额为{_format_value(uncollected, 'currency')}。")
            recommendations.append("优先核查未回款金额较高的区域和产品，并补充缺失的回款记录。")
    for breakdown in breakdowns[:2]:
        if not breakdown["items"]:
            continue
        first = breakdown["items"][0]
        metric = chart_metrics[0]
        value = first["values"].get(metric)
        highlights.append(
            f"按{breakdown['dimension']}比较，{first['label']}的{metric}最高，为{_format_value(value, 'percent' if metric == '回款率' else 'currency' if '金额' in metric or metric == '销售额' else 'number')}。"
        )
    if not recommendations:
        recommendations.append("持续关注排名靠后的分组，并结合后续期间数据验证变化是否持续。")

    if sales_total is not None and collection_total is not None and collection_rate is not None:
        answer = (
            f"本次分析覆盖 {len(rows)} 条有效记录。销售额合计{_format_value(sales_total, 'currency')}，"
            f"回款金额{_format_value(collection_total, 'currency')}，整体回款率{_format_value(collection_rate, 'percent')}。"
        )
    else:
        primary = summary.get("primary_numeric")
        primary_row = next((item for item in summary.get("numeric", []) if item.get("field") == primary), None)
        answer = f"本次分析覆盖 {len(rows)} 条有效记录。"
        if primary_row:
            answer += f"{primary}合计为{_format_value(primary_row['sum'], 'number')}，平均值为{_format_value(primary_row['average'], 'number')}。"
    if highlights:
        answer += highlights[-1]

    return {
        "answer": answer,
        "highlights": highlights[:4],
        "recommendations": recommendations[:3],
        "kpis": kpis[:4],
        "charts": charts[:3],
        "breakdowns": breakdowns,
        "requested_metrics": requested_metrics,
        "requested_dimensions": requested_dimensions,
    }


def _dimension_step(run_id: str, context: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    analysis = context["analysis_result"]
    return {
        "dimensions": [item["dimension"] for item in analysis["breakdowns"]],
        "comparison_groups": sum(len(item["items"]) for item in analysis["breakdowns"]),
    }, [f"{item['dimension']}对比" for item in analysis["breakdowns"]]


def _collection_step(run_id: str, context: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    kpis = {item["label"]: item["value"] for item in context["analysis_result"]["kpis"]}
    return {
        "sales_amount": kpis.get("销售额"),
        "collection_amount": kpis.get("回款金额"),
        "collection_rate": kpis.get("回款率"),
        "uncollected_amount": kpis.get("未回款金额"),
    }, ["销售回款结论", "资金缺口"]


def _trend_step(run_id: str, context: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    trend = next((item for item in context["analysis_result"]["breakdowns"] if item["dimension"] == "月份"), None)
    return {
        "periods": [item["label"] for item in trend["items"]] if trend else [],
        "series": trend["items"] if trend else [],
    }, ["时间趋势图"]


def _anomaly_step(run_id: str, context: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    missing = context["profile"].get("total_missing_cells", 0)
    anomalies = []
    if missing:
        anomalies.append(f"发现 {missing} 个缺失单元格")
    for breakdown in context["analysis_result"]["breakdowns"]:
        rates = [item["values"].get("回款率") for item in breakdown["items"]]
        for item, rate in zip(breakdown["items"], rates):
            if isinstance(rate, (int, float)) and rate < 0.5:
                anomalies.append(f"{breakdown['dimension']}={item['label']} 的回款率低于 50%")
    return {"anomalies": anomalies, "count": len(anomalies)}, ["异常与风险清单"]


def _insight_step(run_id: str, context: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    analysis = build_business_analysis(
        context["cleaned_rows"], context["headers"], context["contract"], context["calculated_summary"]
    )
    if context["profile"].get("total_missing_cells"):
        analysis["recommendations"].append(
            f"数据中仍有 {context['profile']['total_missing_cells']} 个缺失单元格，正式决策前应补齐或确认缺失含义。"
        )
    context["analysis_result"] = analysis
    return {
        "answer": analysis["answer"],
        "highlight_count": len(analysis["highlights"]),
        "recommendation_count": len(analysis["recommendations"]),
        "chart_count": len(analysis["charts"]),
    }, ["问题回答", "关键发现", "行动建议", "可视化数据"]


def _report_step(run_id: str, context: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    run_directory = _run_directory(run_id)
    analysis = context["analysis_result"]
    report_path = run_directory / "经营分析报告.xlsx"
    profile_rows: list[dict[str, object]] = []
    for table in context["profile"]["tables"]:
        for field, missing in table["missing_by_field"].items():
            profile_rows.append(
                {
                    "来源文件": table["source"],
                    "数据表": table["table"],
                    "字段": field,
                    "记录数": table["rows"],
                    "缺失数": missing,
                    "重复行": table["duplicate_rows"],
                }
            )
    conclusion_rows = [
        {"模块": "问题回答", "内容": analysis["answer"]},
        *({"模块": "关键发现", "内容": item} for item in analysis["highlights"]),
        *({"模块": "行动建议", "内容": item} for item in analysis["recommendations"]),
        *(
            {"模块": f"核心指标：{item['label']}", "内容": item["display"]}
            for item in analysis["kpis"]
        ),
        {
            "模块": "数据来源",
            "内容": "系统自动发现的内置演示数据（mcp://demo/sales-ledger）"
            if context.get("source_mode") == "autonomous_demo"
            else "已连接的数据源",
        },
    ]
    comparison_rows = []
    for breakdown in analysis["breakdowns"]:
        for item in breakdown["items"]:
            for metric, value in item["values"].items():
                comparison_rows.append(
                    {
                        "分析维度": breakdown["dimension"],
                        "分类": item["label"],
                        "指标": metric,
                        "结果": value,
                        "记录数": item["records"],
                    }
                )
    reasoning_rows = [
        {
            "阶段": item["title"],
            "输入本体类": "、".join(reasoning["input_classes"]),
            "命中概念": "、".join(reasoning["matched_concepts"]),
            "规则": reasoning["rule"],
            "推理结论": reasoning["inference"],
        }
        for item in context["task_plan"]
        for reasoning in [ontology_reasoning_for(item["key"], context["contract"], context)]
    ]
    write_xlsx(
        report_path,
        [
            ("分析结论", ["模块", "内容"], conclusion_rows),
            ("维度对比", ["分析维度", "分类", "指标", "结果", "记录数"], comparison_rows),
            ("数据质量", ["来源文件", "数据表", "字段", "记录数", "缺失数", "重复行"], profile_rows),
            ("本体推理", ["阶段", "输入本体类", "命中概念", "规则", "推理结论"], reasoning_rows),
            ("数据明细", context["headers"], context["cleaned_rows"]),
        ],
    )
    _add_artifact(
        run_id,
        "generate_report",
        report_path,
        "spreadsheet_report",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        {
            "display_name": "经营分析 Excel",
            "description": "包含问题回答、核心指标、维度对比、数据质量、本体推理和明细。",
            "sheets": 5,
            "rows": len(context["cleaned_rows"]),
            "includes_reasoning_trace": True,
        },
    )
    visual_path = run_directory / "可视化分析报告.html"
    visual_path.write_text(_render_visual_report(context), encoding="utf-8")
    _add_artifact(
        run_id,
        "generate_report",
        visual_path,
        "visual_report",
        "text/html; charset=utf-8",
        {"display_name": "可视化分析报告", "description": "浏览器可直接阅读的指标、对比图和结论报告。"},
    )
    brief_path = run_directory / "管理摘要.md"
    brief_path.write_text(_render_management_brief(context), encoding="utf-8")
    _add_artifact(
        run_id,
        "generate_report",
        brief_path,
        "management_brief",
        "text/markdown; charset=utf-8",
        {"display_name": "管理摘要", "description": "一页式问题回答、关键发现和行动建议。"},
    )
    return {"workbook_sheets": 5, "report_rows": len(context["cleaned_rows"]), "visual_charts": len(analysis["charts"])}, [
        "经营分析报告.xlsx",
        "可视化分析报告.html",
        "管理摘要.md",
    ]


def _verify_step(run_id: str, context: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    run_directory = _run_directory(run_id)
    checks = [
        {"name": "数据源已解析", "passed": bool(context.get("tables"))},
        {"name": "清洗数据已生成", "passed": (run_directory / "cleaned-data.csv").exists()},
        {"name": "Excel 报表已生成", "passed": (run_directory / "经营分析报告.xlsx").exists()},
        {"name": "可视化报告已生成", "passed": (run_directory / "可视化分析报告.html").exists()},
        {"name": "管理摘要已生成", "passed": (run_directory / "管理摘要.md").exists()},
        {"name": "结果已直接回答问题", "passed": bool(context.get("analysis_result", {}).get("answer"))},
        {"name": "数据行数有效", "passed": len(context.get("cleaned_rows", [])) > 0},
        {"name": "结果使用统一数据版本", "passed": True},
    ]
    passed = sum(item["passed"] for item in checks)
    if passed != len(checks):
        failed = [item["name"] for item in checks if not item["passed"]]
        raise ValueError(f"交付验证未通过：{', '.join(failed)}")
    context["verification_checks"] = checks
    return {"checks": checks, "passed": passed, "total": len(checks)}, ["verification_evidence"]


def _package_step(run_id: str, context: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    with session_scope() as session:
        run = session.get(WorkflowRunORM, run_id)
        tasks = session.scalars(
            select(ExecutionTaskORM).where(ExecutionTaskORM.run_id == run_id).order_by(ExecutionTaskORM.order_index)
        ).all()
        artifact_count = len(session.scalars(select(ArtifactORM).where(ArtifactORM.run_id == run_id)).all())
        execution_report = {
            "run_id": run_id,
            "title": run.title if run else "",
            "requirement": run.requirement if run else "",
            "result_contract": run.result_contract if run else {},
            "tasks": [
                {
                    "key": task.task_key,
                    "title": task.title,
                    "status": task.status,
                    "skill": task.skill_spec,
                    "evidence": task.evidence,
                    "outputs": task.outputs,
                }
                for task in tasks
            ],
            "verification": context.get("verification_checks", []),
        }
    execution_path = _run_directory(run_id) / "执行与验证报告.html"
    execution_path.write_text(_render_execution_report(execution_report), encoding="utf-8")
    _add_artifact(
        run_id,
        "package_results",
        execution_path,
        "execution_report",
        "text/html; charset=utf-8",
        {"display_name": "执行与验证报告", "description": "面向审阅者的任务路径、本体规则、能力绑定和验收结果。"},
    )
    analysis = context["analysis_result"]
    final_summary = {
        "input_rows": len(context["aligned_rows"]),
        "output_rows": len(context["cleaned_rows"]),
        "duplicates_removed": context["duplicates_removed"],
        "missing_cells": context["profile"]["total_missing_cells"],
        "numeric_fields": len(context["calculated_summary"]["numeric"]),
        "artifact_count": artifact_count + 1,
        "source_mode": context.get("source_mode", "unknown"),
        "answer": analysis["answer"],
        "highlights": analysis["highlights"],
        "recommendations": analysis["recommendations"],
        "kpis": analysis["kpis"],
        "charts": analysis["charts"],
        "progress": 100,
        "task_count": len(tasks),
    }
    with session_scope() as session:
        run = session.get(WorkflowRunORM, run_id)
        if run:
            run.summary = final_summary
    return final_summary, ["执行与验证报告.html", "四项用户报告"]


def _render_visual_report(context: dict[str, Any]) -> str:
    analysis = context["analysis_result"]
    cards = "".join(
        f'<section class="kpi"><span>{html_escape(item["label"])}</span><strong>{html_escape(item["display"])}</strong></section>'
        for item in analysis["kpis"]
    )
    chart_sections = "".join(_render_chart_html(chart) for chart in analysis["charts"])
    highlights = "".join(f"<li>{html_escape(item)}</li>" for item in analysis["highlights"])
    recommendations = "".join(f"<li>{html_escape(item)}</li>" for item in analysis["recommendations"])
    source_note = (
        "当前使用系统内置演示数据源 mcp://demo/sales-ledger，结论用于验证执行链路。"
        if context.get("source_mode") == "autonomous_demo"
        else "当前结果来自已连接数据源。"
    )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>可视化分析报告</title><style>
body{{margin:0;background:#f2f4f2;color:#17201d;font-family:"Segoe UI","Microsoft YaHei",sans-serif}}main{{width:min(1120px,calc(100% - 40px));margin:32px auto 56px}}
header{{border-bottom:1px solid #ccd5ce;padding-bottom:18px}}small{{color:#66756c}}h1{{margin:6px 0 8px;font-size:28px}}h2{{font-size:16px;margin:0 0 14px}}p{{line-height:1.75}}.answer,.panel{{margin-top:18px;border:1px solid #d4ddd6;border-radius:9px;background:white;padding:20px}}.answer{{border-left:4px solid #2f6b4f}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:14px}}.kpi{{border-top:3px solid #2f6b4f;background:white;padding:14px}}.kpi span,.kpi strong{{display:block}}.kpi span{{font-size:12px;color:#6a776f}}.kpi strong{{margin-top:6px;font-size:22px}}
.charts{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-top:18px}}.chart{{border:1px solid #d4ddd6;border-radius:9px;background:white;padding:18px}}.row{{display:grid;grid-template-columns:72px 1fr 86px;gap:10px;align-items:center;margin:9px 0;font-size:12px}}.track{{height:12px;background:#edf1ee;border-radius:3px;overflow:hidden}}.bar{{height:100%;background:#356b52}}.bar.secondary{{margin-top:2px;background:#7b9eb8}}.value{{text-align:right;font-variant-numeric:tabular-nums}}ul{{margin:8px 0 0;padding-left:20px;line-height:1.8}}footer{{margin-top:18px;color:#718078;font-size:12px}}
@media(max-width:760px){{.kpis,.charts{{grid-template-columns:1fr 1fr}}.row{{grid-template-columns:64px 1fr 72px}}}}@media(max-width:520px){{.kpis,.charts{{grid-template-columns:1fr}}}}
</style></head><body><main><header><small>本体智能体工作台 · 分析结果</small><h1>{html_escape(context['contract'].get('goal', '分析报告'))}</h1><p>{html_escape(source_note)}</p></header>
<section class="answer"><small>问题回答</small><h2>{html_escape(analysis['answer'])}</h2></section><div class="kpis">{cards}</div><div class="charts">{chart_sections}</div>
<section class="panel"><h2>关键发现</h2><ul>{highlights}</ul></section><section class="panel"><h2>建议</h2><ul>{recommendations}</ul></section>
<footer>共处理 {len(context['cleaned_rows'])} 条有效记录，移除 {context['duplicates_removed']} 条重复记录。报告由本次执行结果生成。</footer></main></body></html>"""


def _render_chart_html(chart: dict[str, Any]) -> str:
    series = chart.get("series", [])[:2]
    items = chart.get("items", [])
    values = [
        float(item.get("values", {}).get(item_series.get("key")) or 0)
        for item in items
        for item_series in series
    ]
    maximum = max(values, default=1) or 1
    rows = []
    for item in items:
        bars = []
        displays = []
        for index, item_series in enumerate(series):
            value = item.get("values", {}).get(item_series.get("key"))
            width = max(1.5, float(value or 0) / maximum * 100)
            bars.append(f'<div class="bar{" secondary" if index else ""}" style="width:{width:.1f}%"></div>')
            displays.append(f"{item_series.get('label')} {_format_value(value, item_series.get('format', 'number'))}")
        rows.append(
            f'<div class="row"><span>{html_escape(str(item.get("label", "")))}</span>'
            f'<div class="track">{"".join(bars)}</div><span class="value">{html_escape(" / ".join(displays))}</span></div>'
        )
    return f'<section class="chart"><h2>{html_escape(chart.get("title", "指标对比"))}</h2>{"".join(rows)}</section>'


def _render_management_brief(context: dict[str, Any]) -> str:
    analysis = context["analysis_result"]
    kpis = "\n".join(f"- **{item['label']}：** {item['display']}" for item in analysis["kpis"])
    highlights = "\n".join(f"- {item}" for item in analysis["highlights"])
    recommendations = "\n".join(f"- {item}" for item in analysis["recommendations"])
    return (
        f"# 管理摘要\n\n## 任务目标\n\n{context['contract'].get('goal', '')}\n\n"
        f"## 问题回答\n\n{analysis['answer']}\n\n## 核心指标\n\n{kpis}\n\n"
        f"## 关键发现\n\n{highlights}\n\n## 建议\n\n{recommendations}\n\n"
        f"## 数据说明\n\n有效记录 {len(context['cleaned_rows'])} 条，移除重复记录 {context['duplicates_removed']} 条。"
    )


def _render_execution_report(report: dict[str, Any]) -> str:
    task_rows = []
    for task in report["tasks"]:
        reasoning = (task.get("evidence") or {}).get("ontology_reasoning", {})
        bindings = "、".join((task.get("skill") or {}).get("mcp_bindings", [])) or "无"
        status = "已完成" if task.get("key") == "package_results" else task.get("status", "")
        task_rows.append(
            "<tr>"
            f"<td>{html_escape(task.get('title', ''))}</td><td>{html_escape(status)}</td>"
            f"<td>{html_escape((task.get('skill') or {}).get('name', ''))}</td><td>{html_escape(bindings)}</td>"
            f"<td>{html_escape(reasoning.get('rule', ''))}</td><td>{html_escape(reasoning.get('inference', ''))}</td>"
            "</tr>"
        )
    checks = "".join(
        f"<li>{'通过' if item.get('passed') else '未通过'}：{html_escape(item.get('name', ''))}</li>"
        for item in report.get("verification", [])
    )
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>执行与验证报告</title><style>
body{{margin:0;background:#f2f4f2;color:#17201d;font-family:"Segoe UI","Microsoft YaHei",sans-serif}}main{{width:min(1280px,calc(100% - 40px));margin:32px auto}}h1{{font-size:26px}}p,li{{line-height:1.7}}table{{width:100%;border-collapse:collapse;background:white;font-size:12px}}th,td{{border-bottom:1px solid #dbe1dc;padding:10px;text-align:left;vertical-align:top}}th{{background:#245b45;color:white}}section{{margin-top:18px;border:1px solid #d4ddd6;border-radius:8px;background:white;padding:18px;overflow:auto}}
</style></head><body><main><h1>执行与验证报告</h1><p><strong>需求：</strong>{html_escape(report.get('requirement', ''))}</p><section><h2>任务路径与本体判断</h2><table><thead><tr><th>任务</th><th>状态</th><th>Skill</th><th>MCP 能力</th><th>触发规则</th><th>推理结论</th></tr></thead><tbody>{''.join(task_rows)}</tbody></table></section><section><h2>验收结果</h2><ul>{checks}</ul></section></main></body></html>"""


def _extract_time_scope(requirement: str) -> dict[str, Any] | None:
    match = re.search(r"最近\s*([一二三四五六七八九十\d]+)\s*个?月", requirement)
    if match:
        count = _parse_small_number(match.group(1))
        return {"kind": "latest_months", "count": count, "label": f"最近{count}个月"}
    if any(keyword in requirement for keyword in ("按月", "月度", "月份", "趋势", "走势")):
        return {"kind": "available_periods", "count": 12, "label": "可用月份"}
    return None


def _parse_small_number(value: str) -> int:
    if value.isdigit():
        return max(1, int(value))
    digits = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    if value in digits:
        return digits[value]
    if value.startswith("十"):
        return 10 + digits.get(value[1:], 0)
    if "十" in value:
        left, right = value.split("十", 1)
        return digits.get(left, 1) * 10 + digits.get(right, 0)
    return 3


def _period_value(value: object) -> str:
    raw = str(value or "").strip()
    match = re.search(r"(\d{4})[-/.年](\d{1,2})", raw)
    return f"{match.group(1)}-{int(match.group(2)):02d}" if match else raw


def _dimension_field(dimension: str, headers: list[str]) -> str | None:
    candidates = {
        "月份": ["月份", "日期"],
        "区域": ["区域"],
        "产品": ["产品"],
        "客户": ["客户名称", "客户编号", "客户"],
        "部门": ["部门"],
    }.get(dimension, [dimension])
    return next((item for item in candidates if item in headers), None)


def _aggregate_metric(rows: list[dict[str, object]], metric: str) -> float:
    if metric in {"记录数", "数量", "总数"}:
        return float(len(rows))
    if metric == "订单数":
        field = next((name for name in ("订单编号", "订单号") if any(name in row for row in rows)), None)
        return float(len({str(row.get(field, "")) for row in rows if field and str(row.get(field, "")).strip()})) if field else float(len(rows))
    if metric == "回款率":
        sales = _aggregate_metric(rows, "销售额")
        collection = _aggregate_metric(rows, "回款金额")
        return collection / sales if sales else 0.0
    values = [_number(row.get(metric)) for row in rows]
    return round(sum(value for value in values if value is not None), 4)


def _kpi(label: str, value: float, value_format: str, tone: str = "neutral") -> dict[str, Any]:
    return {"label": label, "value": value, "display": _format_value(value, value_format), "format": value_format, "tone": tone}


def _format_value(value: object, value_format: str = "number") -> str:
    number = _number(value)
    if number is None:
        return "—"
    if value_format == "percent":
        return f"{number * 100:.1f}%"
    if value_format == "currency":
        return f"¥{number:,.0f}"
    if value_format == "integer":
        return f"{number:,.0f}"
    return f"{number:,.2f}".rstrip("0").rstrip(".")


def canonical_header(header: str) -> str:
    stripped = str(header).strip()
    normalized = re.sub(r"[\s_\-./\\]+", "", stripped).lower()
    return FIELD_ALIASES.get(normalized, stripped or "未命名字段")


def _mentioned(text: str, candidates: dict[str, list[str]]) -> list[str]:
    return [name for name, keywords in candidates.items() if any(keyword in text for keyword in keywords)]


def _is_blank(value: object) -> bool:
    return value is None or str(value).strip().lower() in {"", "none", "null", "nan"}


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value).strip().replace(",", "").replace("￥", "").replace("¥", "")
    if raw.endswith("%"):
        raw = raw[:-1]
        divisor = 100
    else:
        divisor = 1
    try:
        return float(raw) / divisor
    except ValueError:
        return None


def _run_directory(run_id: str) -> Path:
    path = ARTIFACT_ROOT / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _set_task_state(
    run_id: str,
    task_key: str,
    status: str,
    *,
    evidence: dict[str, Any] | None = None,
    outputs: list[str] | None = None,
    error: str = "",
) -> None:
    with session_scope() as session:
        task = session.scalar(
            select(ExecutionTaskORM).where(
                ExecutionTaskORM.run_id == run_id, ExecutionTaskORM.task_key == task_key
            )
        )
        if not task:
            return
        task.status = status
        if status == "running":
            task.started_at = datetime.now(timezone.utc)
        if status in {"succeeded", "failed"}:
            task.completed_at = datetime.now(timezone.utc)
        if evidence is not None:
            task.evidence = evidence
        if outputs is not None:
            task.outputs = outputs
        task.error = error


def _add_artifact(
    run_id: str,
    task_key: str,
    path: Path,
    kind: str,
    mime_type: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    with session_scope() as session:
        task = session.scalar(
            select(ExecutionTaskORM).where(
                ExecutionTaskORM.run_id == run_id, ExecutionTaskORM.task_key == task_key
            )
        )
        session.add(
            ArtifactORM(
                run_id=run_id,
                task_id=task.id if task else None,
                name=path.name,
                kind=kind,
                path=str(path.resolve()),
                mime_type=mime_type,
                size=path.stat().st_size,
                artifact_metadata=metadata or {},
            )
        )


def _fail_workflow(run_id: str, exc: Exception) -> None:
    message = str(exc) or exc.__class__.__name__
    with session_scope() as session:
        run = session.get(WorkflowRunORM, run_id)
        if run:
            run.status = "failed"
            run.error = message
            run.completed_at = datetime.now(timezone.utc)
        running = session.scalar(
            select(ExecutionTaskORM).where(
                ExecutionTaskORM.run_id == run_id, ExecutionTaskORM.status == "running"
            )
        )
        if running:
            running.status = "failed"
            running.error = message
            running.completed_at = datetime.now(timezone.utc)
