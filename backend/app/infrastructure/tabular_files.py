"""CSV/XLSX 的轻量读写能力，只使用 Python 标准库。

它是首个数据 MCP 能力适配层的本地实现：上层 Skill 只依赖 read_table /
write_table 能力，后续可以无缝替换为数据库、网盘或远程 MCP 服务。
"""

from __future__ import annotations

import csv
import re
import zipfile
from dataclasses import dataclass
from html import escape
from pathlib import Path
from xml.etree import ElementTree as ET


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


@dataclass
class TableData:
    name: str
    source: str
    headers: list[str]
    rows: list[dict[str, object]]


def read_tabular(path: Path) -> list[TableData]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return [_read_csv(path)]
    if suffix == ".xlsx":
        return _read_xlsx(path)
    raise ValueError(f"不支持的文件格式：{suffix or '未知'}；首版支持 CSV 和 XLSX。")


def _read_csv(path: Path) -> TableData:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                reader = csv.reader(handle)
                matrix = list(reader)
            break
        except UnicodeDecodeError as exc:
            last_error = exc
    else:
        raise ValueError(f"无法识别 CSV 编码：{path.name}") from last_error

    headers, rows = _matrix_to_rows(matrix)
    return TableData(name=path.stem, source=path.name, headers=headers, rows=rows)


def _read_xlsx(path: Path) -> list[TableData]:
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise ValueError(f"{path.name} 不是有效的 XLSX 文件。") from exc

    with archive:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall(f"{{{MAIN_NS}}}si"):
                shared_strings.append("".join(node.text or "" for node in item.iter(f"{{{MAIN_NS}}}t")))

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in relationships.findall(f"{{{PKG_REL_NS}}}Relationship")
        }

        tables: list[TableData] = []
        for sheet in workbook.findall(f".//{{{MAIN_NS}}}sheet"):
            relation_id = sheet.attrib.get(f"{{{REL_NS}}}id", "")
            target = targets.get(relation_id, "")
            if not target:
                continue
            sheet_path = target.lstrip("/")
            if not sheet_path.startswith("xl/"):
                sheet_path = f"xl/{sheet_path}"
            sheet_path = str(Path(sheet_path)).replace("\\", "/")
            if sheet_path not in archive.namelist():
                continue
            matrix = _read_sheet_xml(archive.read(sheet_path), shared_strings)
            headers, rows = _matrix_to_rows(matrix)
            if headers:
                tables.append(
                    TableData(
                        name=sheet.attrib.get("name", path.stem),
                        source=path.name,
                        headers=headers,
                        rows=rows,
                    )
                )
        if not tables:
            raise ValueError(f"{path.name} 中没有可读取的数据工作表。")
        return tables


def _read_sheet_xml(content: bytes, shared_strings: list[str]) -> list[list[object]]:
    root = ET.fromstring(content)
    matrix: list[list[object]] = []
    for row_node in root.findall(f".//{{{MAIN_NS}}}sheetData/{{{MAIN_NS}}}row"):
        values: dict[int, object] = {}
        for cell in row_node.findall(f"{{{MAIN_NS}}}c"):
            reference = cell.attrib.get("r", "A1")
            letters = re.match(r"[A-Z]+", reference)
            index = _column_index(letters.group(0) if letters else "A")
            cell_type = cell.attrib.get("t")
            value_node = cell.find(f"{{{MAIN_NS}}}v")
            if cell_type == "inlineStr":
                value = "".join(node.text or "" for node in cell.iter(f"{{{MAIN_NS}}}t"))
            elif value_node is None:
                value = ""
            elif cell_type == "s":
                position = int(value_node.text or "0")
                value = shared_strings[position] if position < len(shared_strings) else ""
            elif cell_type == "b":
                value = (value_node.text or "0") == "1"
            else:
                raw = value_node.text or ""
                try:
                    value = float(raw) if "." in raw else int(raw)
                except ValueError:
                    value = raw
            values[index] = value
        width = max(values, default=-1) + 1
        matrix.append([values.get(index, "") for index in range(width)])
    return matrix


def _matrix_to_rows(matrix: list[list[object]]) -> tuple[list[str], list[dict[str, object]]]:
    matrix = [row for row in matrix if any(str(value).strip() for value in row)]
    if not matrix:
        return [], []
    headers = _unique_headers(matrix[0])
    rows: list[dict[str, object]] = []
    for source_row in matrix[1:]:
        row = {header: source_row[index] if index < len(source_row) else "" for index, header in enumerate(headers)}
        if any(str(value).strip() for value in row.values()):
            rows.append(row)
    return headers, rows


def _unique_headers(values: list[object]) -> list[str]:
    headers: list[str] = []
    counts: dict[str, int] = {}
    for index, raw in enumerate(values, start=1):
        base = str(raw).strip() or f"column_{index}"
        counts[base] = counts.get(base, 0) + 1
        headers.append(base if counts[base] == 1 else f"{base}_{counts[base]}")
    return headers


def _column_index(letters: str) -> int:
    result = 0
    for letter in letters:
        result = result * 26 + ord(letter) - 64
    return result - 1


def _column_name(index: int) -> str:
    result = ""
    current = index + 1
    while current:
        current, remainder = divmod(current - 1, 26)
        result = chr(65 + remainder) + result
    return result


def write_csv(path: Path, headers: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in headers})


def write_xlsx(path: Path, sheets: list[tuple[str, list[str], list[dict[str, object]]]]) -> None:
    """写出无需第三方依赖的基础 XLSX，包含表头、筛选和冻结首行。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    sheet_names = _sheet_names([name for name, _, _ in sheets])
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        overrides = "".join(
            f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for index in range(1, len(sheets) + 1)
        )
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            f"{overrides}</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        workbook_sheets = "".join(
            f'<sheet name="{escape(name, quote=True)}" sheetId="{index}" r:id="rId{index}"/>'
            for index, name in enumerate(sheet_names, start=1)
        )
        archive.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<workbook xmlns="{MAIN_NS}" xmlns:r="{REL_NS}"><sheets>{workbook_sheets}</sheets></workbook>',
        )
        workbook_rels = "".join(
            f'<Relationship Id="rId{index}" Type="{REL_NS}/worksheet" Target="worksheets/sheet{index}.xml"/>'
            for index in range(1, len(sheets) + 1)
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="{PKG_REL_NS}">{workbook_rels}'
            f'<Relationship Id="rId{len(sheets) + 1}" Type="{REL_NS}/styles" Target="styles.xml"/>'
            "</Relationships>",
        )
        archive.writestr("xl/styles.xml", _styles_xml())
        for index, (_, headers, rows) in enumerate(sheets, start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", _sheet_xml(headers, rows))


def _sheet_names(names: list[str]) -> list[str]:
    result: list[str] = []
    used: set[str] = set()
    for raw in names:
        base = re.sub(r"[\\/*?:\[\]]", "_", raw).strip()[:31] or "Sheet"
        candidate = base
        suffix = 2
        while candidate.lower() in used:
            ending = f"_{suffix}"
            candidate = f"{base[:31 - len(ending)]}{ending}"
            suffix += 1
        used.add(candidate.lower())
        result.append(candidate)
    return result


def _sheet_xml(headers: list[str], rows: list[dict[str, object]]) -> str:
    matrix = [dict(zip(headers, headers)), *rows]
    xml_rows: list[str] = []
    for row_index, row in enumerate(matrix, start=1):
        cells: list[str] = []
        for column_index, header in enumerate(headers):
            value = row.get(header, "")
            reference = f"{_column_name(column_index)}{row_index}"
            style = ' s="1"' if row_index == 1 else ""
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cells.append(f'<c r="{reference}"{style}><v>{value}</v></c>')
            else:
                text = escape(str(value) if value is not None else "")
                cells.append(f'<c r="{reference}" t="inlineStr"{style}><is><t xml:space="preserve">{text}</t></is></c>')
        xml_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    last_column = _column_name(max(len(headers) - 1, 0))
    dimension = f"A1:{last_column}{max(len(matrix), 1)}"
    auto_filter = f'<autoFilter ref="A1:{last_column}{max(len(matrix), 1)}"/>' if headers else ""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{MAIN_NS}"><dimension ref="{dimension}"/>'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        f'<sheetData>{"".join(xml_rows)}</sheetData>{auto_filter}</worksheet>'
    )


def _styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<styleSheet xmlns="{MAIN_NS}">'
        '<fonts count="2"><font><sz val="11"/><name val="Aptos"/></font><font><b/><sz val="11"/><name val="Aptos"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        "</styleSheet>"
    )
