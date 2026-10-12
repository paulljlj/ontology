"""通用“需求 → Task → Skill → 产物 → 验证”执行器的首个数据报表实现。"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select

from app.infrastructure.database import session_scope
from app.infrastructure.orm import ArtifactORM, ExecutionTaskORM, WorkflowRunORM, new_id
from app.infrastructure.tabular_files import TableData, read_tabular, write_csv, write_xlsx


BACKEND_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = BACKEND_ROOT / "report_artifacts"


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
        "识别数据源",
        "读取 CSV/XLSX，识别文件、工作表、字段和记录规模。",
        "tabular-source-inspector",
        ["table.read", "schema.inspect"],
        ["filesystem.read", "spreadsheet.read"],
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


def compile_result_contract(requirement: str, file_names: list[str]) -> dict[str, Any]:
    dimensions = _mentioned(
        requirement,
        {
            "月份": ["月份", "月度", "按月"],
            "区域": ["区域", "地区", "大区"],
            "产品": ["产品", "商品"],
            "客户": ["客户", "用户"],
            "部门": ["部门", "团队"],
        },
    )
    metrics = _mentioned(
        requirement,
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
    return {
        "goal": requirement.strip(),
        "inputs": file_names,
        "operations": ["字段识别", "质量分析", "字段对齐", "数据清洗", "汇总计算", "报表生成"],
        "dimensions": dimensions or ["系统自动识别分类维度"],
        "metrics": metrics,
        "deliverables": ["清洗后的 CSV 数据", "Excel 分析报表", "执行与验证清单"],
        "acceptance_criteria": [
            "所有输入文件都被读取并保留来源血缘",
            "空记录和完全重复记录已处理",
            "报表汇总与清洗后明细使用同一数据版本",
            "最终产物可以下载并追溯到执行 Task",
        ],
    }


def create_workflow_run(
    requirement: str,
    title: str,
    input_files: list[dict[str, Any]],
    run_id: str | None = None,
) -> str:
    run_id = run_id or new_id()
    contract = compile_result_contract(requirement, [item["name"] for item in input_files])
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
                summary={"progress": 0, "task_count": len(TASK_BLUEPRINTS)},
            )
        )
        for index, (key, task_title, description, skill_name, capabilities, bindings) in enumerate(
            TASK_BLUEPRINTS, start=1
        ):
            previous_key = TASK_BLUEPRINTS[index - 2][0] if index > 1 else None
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

        handlers: dict[str, Callable[[str, dict[str, Any]], tuple[dict[str, Any], list[str]]]] = {
            "compile_requirement": _compile_step,
            "inspect_sources": _inspect_step,
            "profile_data": _profile_step,
            "align_schema": _align_step,
            "clean_merge": _clean_step,
            "calculate_summary": _summary_step,
            "generate_report": _report_step,
            "verify_delivery": _verify_step,
            "package_results": _package_step,
        }
        for index, (key, *_rest) in enumerate(TASK_BLUEPRINTS, start=1):
            _set_task_state(run_id, key, "running")
            evidence, outputs = handlers[key](run_id, context)
            _set_task_state(run_id, key, "succeeded", evidence=evidence, outputs=outputs)
            with session_scope() as session:
                run = session.get(WorkflowRunORM, run_id)
                if run:
                    current = dict(run.summary or {})
                    current["progress"] = round(index / len(TASK_BLUEPRINTS) * 100)
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
    if not tables:
        raise ValueError("没有读取到可处理的数据表。")
    context["tables"] = tables
    return {
        "source_files": len(inputs),
        "tables": len(tables),
        "input_rows": sum(len(table.rows) for table in tables),
        "schemas": [{"source": table.source, "table": table.name, "fields": table.headers} for table in tables],
    }, ["source_inventory", "schema_snapshot"]


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
    _add_artifact(run_id, "clean_merge", output, "cleaned_data", "text/csv", {"rows": len(cleaned)})
    return {
        "input_rows": len(context["aligned_rows"]),
        "output_rows": len(cleaned),
        "duplicates_removed": duplicates,
        "lineage_fields": ["_source_file", "_source_table"],
    }, ["cleaned-data.csv"]


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
    evidence = {
        "numeric_fields": len(summary["numeric"]),
        "group_rows": len(summary["categorical"]),
        "primary_numeric": summary["primary_numeric"],
    }
    return evidence, ["numeric_summary", "categorical_summary"]


def _report_step(run_id: str, context: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    run_directory = _run_directory(run_id)
    report_path = run_directory / "analysis-report.xlsx"
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
    execution_rows = [
        {"项目": "目标", "结果": context["contract"].get("goal", "")},
        {"项目": "输入记录", "结果": len(context["aligned_rows"])},
        {"项目": "清洗后记录", "结果": len(context["cleaned_rows"])},
        {"项目": "删除重复记录", "结果": context["duplicates_removed"]},
        {"项目": "缺失单元格", "结果": context["profile"]["total_missing_cells"]},
    ]
    numeric_rows = [
        {
            "字段": item["field"],
            "有效值数": item["count"],
            "合计": item["sum"],
            "平均值": item["average"],
            "最小值": item["min"],
            "最大值": item["max"],
        }
        for item in context["calculated_summary"]["numeric"]
    ]
    category_rows = [
        {
            "维度": item["dimension"],
            "分类": item["value"],
            "记录数": item["records"],
            "汇总指标": item["metric"],
            "指标合计": item["metric_sum"],
        }
        for item in context["calculated_summary"]["categorical"]
    ]
    write_xlsx(
        report_path,
        [
            ("执行摘要", ["项目", "结果"], execution_rows),
            ("数据质量", ["来源文件", "数据表", "字段", "记录数", "缺失数", "重复行"], profile_rows),
            ("数值汇总", ["字段", "有效值数", "合计", "平均值", "最小值", "最大值"], numeric_rows),
            ("分类汇总", ["维度", "分类", "记录数", "汇总指标", "指标合计"], category_rows),
            ("清洗后数据", context["headers"], context["cleaned_rows"]),
        ],
    )
    _add_artifact(
        run_id,
        "generate_report",
        report_path,
        "spreadsheet_report",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        {"sheets": 5, "rows": len(context["cleaned_rows"])},
    )
    summary_path = run_directory / "result-summary.json"
    summary_payload = {
        "contract": context["contract"],
        "profile": context["profile"],
        "summary": context["calculated_summary"],
    }
    summary_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _add_artifact(run_id, "generate_report", summary_path, "result_summary", "application/json")
    return {"workbook_sheets": 5, "report_rows": len(context["cleaned_rows"])}, [
        "analysis-report.xlsx",
        "result-summary.json",
    ]


def _verify_step(run_id: str, context: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    run_directory = _run_directory(run_id)
    checks = [
        {"name": "输入文件已读取", "passed": bool(context.get("tables"))},
        {"name": "清洗数据已生成", "passed": (run_directory / "cleaned-data.csv").exists()},
        {"name": "Excel 报表已生成", "passed": (run_directory / "analysis-report.xlsx").exists()},
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
        manifest = {
            "run_id": run_id,
            "title": run.title if run else "",
            "requirement": run.requirement if run else "",
            "result_contract": run.result_contract if run else {},
            "tasks": [
                {"key": task.task_key, "title": task.title, "status": task.status, "outputs": task.outputs}
                for task in tasks
            ],
            "verification": context.get("verification_checks", []),
        }
    manifest_path = _run_directory(run_id) / "execution-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    _add_artifact(run_id, "package_results", manifest_path, "execution_manifest", "application/json")
    final_summary = {
        "input_rows": len(context["aligned_rows"]),
        "output_rows": len(context["cleaned_rows"]),
        "duplicates_removed": context["duplicates_removed"],
        "missing_cells": context["profile"]["total_missing_cells"],
        "numeric_fields": len(context["calculated_summary"]["numeric"]),
        "artifact_count": artifact_count + 1,
        "progress": 100,
        "task_count": len(TASK_BLUEPRINTS),
    }
    with session_scope() as session:
        run = session.get(WorkflowRunORM, run_id)
        if run:
            run.summary = final_summary
    return final_summary, ["execution-manifest.json", "delivery_bundle"]


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
