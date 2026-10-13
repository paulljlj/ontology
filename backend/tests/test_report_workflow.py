from pathlib import Path

from app.application.report_workflow import (
    align_tables,
    build_summary,
    canonical_header,
    clean_rows,
    compile_result_contract,
    profile_tables,
)
from app.infrastructure.tabular_files import read_tabular, write_xlsx


FIXTURE = Path(__file__).parent / "fixtures" / "sample_sales.csv"


def test_compiles_requirement_contract():
    contract = compile_result_contract(
        "按月份、区域和产品统计销售额、订单数和回款率，生成报表。",
        ["sales.xlsx"],
    )
    assert contract["dimensions"] == ["月份", "区域", "产品"]
    assert {"销售额", "订单数", "回款率"}.issubset(contract["metrics"])
    assert "Excel 分析报表" in contract["deliverables"]


def test_contract_can_run_without_uploaded_files():
    contract = compile_result_contract("自动发现数据源并生成销售分析报告。", [])
    assert contract["inputs"] == ["Agent 通过 DataSourceResolver / MCP 自动发现"]
    assert any("自动选择" in item for item in contract["acceptance_criteria"])


def test_profiles_aligns_cleans_and_summarizes_data():
    tables = read_tabular(FIXTURE)
    profile = profile_tables(tables)
    assert profile["tables"][0]["rows"] == 5
    assert profile["tables"][0]["duplicate_rows"] == 1

    rows, headers, mappings = align_tables(tables)
    assert canonical_header("订单号") == "订单编号"
    assert any(item["to"] == "销售额" for item in mappings)

    cleaned, duplicate_count = clean_rows(rows, headers)
    assert duplicate_count == 1
    assert len(cleaned) == 4

    summary = build_summary(cleaned, headers)
    sales = next(item for item in summary["numeric"] if item["field"] == "销售额")
    assert sales["sum"] == 40000
    assert any(item["dimension"] == "区域" for item in summary["categorical"])


def test_stdlib_xlsx_round_trip(tmp_path):
    target = tmp_path / "report.xlsx"
    write_xlsx(
        target,
        [("数据", ["区域", "销售额"], [{"区域": "华东", "销售额": 120}, {"区域": "华南", "销售额": 80}])],
    )
    table = read_tabular(target)[0]
    assert table.headers == ["区域", "销售额"]
    assert table.rows[0] == {"区域": "华东", "销售额": 120}
