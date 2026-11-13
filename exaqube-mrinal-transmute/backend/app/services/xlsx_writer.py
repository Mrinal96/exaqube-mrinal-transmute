"""Deterministic native XLSX rendering from the canonical DocumentIR."""

from __future__ import annotations

import json
import re
from datetime import datetime
from io import BytesIO
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.formula import Tokenizer
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter, range_boundaries
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.worksheet.worksheet import Worksheet

from app.models.intermediate import DocumentIR, IRBlock, IRSection, SourceLocation
from app.services.native_writer_errors import UnsupportedIRContentError


IR_XLSX_SCHEMA_VERSION = "native-ir-xlsx-v1"
_SAFE_FUNCTIONS = {
    "ABS", "AND", "AVERAGE", "AVERAGEIF", "AVERAGEIFS", "COUNT", "COUNTA", "COUNTBLANK",
    "COUNTIF", "COUNTIFS", "DATE", "DAY", "EDATE", "EOMONTH", "HLOOKUP", "IF", "IFERROR",
    "IFS", "INDEX", "INT", "LEFT", "LEN", "LOWER", "MATCH", "MAX", "MEDIAN", "MID", "MIN",
    "MOD", "MONTH", "NOT", "OR", "POWER", "PRODUCT", "PROPER", "ROUND", "ROUNDDOWN", "ROUNDUP",
    "SUBSTITUTE", "SUBTOTAL", "SUM", "SUMIF", "SUMIFS", "SUMPRODUCT", "TEXT", "TRIM", "UPPER",
    "VALUE", "VLOOKUP", "YEAR",
}
_FORBIDDEN_FORMULA_FUNCTIONS = {
    "CALL", "DDE", "EXEC", "FILTERXML", "HYPERLINK", "IMAGE", "REGISTER.ID", "RTD", "SHELL", "WEBSERVICE",
}
_TEXT_PREFIXES = ("=", "+", "-", "@")
_HEADER_FILL = PatternFill("solid", fgColor="E6EBF4")
_TITLE_FILL = PatternFill("solid", fgColor="202D48")


def render_xlsx(document_ir: DocumentIR) -> bytes:
    """Render IR content and provenance without invoking an LLM or evaluating text as formulas."""
    ir = _validated_ir(document_ir)
    workbook = Workbook()
    workbook.remove(workbook.active)
    source_sheet_map: dict[str, Worksheet] = {}
    tables: list[tuple[str, IRBlock, list[str]]] = []
    formulas: list[tuple[str, IRBlock, list[str]]] = []
    unsupported: list[str] = []

    def inspect_sections(sections: list[IRSection], parents: list[str]) -> None:
        for section in sections:
            path = [*parents, section.title]
            for block in section.blocks:
                if block.kind in {"chart", "diagram"}:
                    unsupported.append(f"{block.kind} block {block.id}")
                elif block.kind == "table":
                    tables.append((" / ".join(path), block, path))
                elif block.kind == "formula":
                    formulas.append((" / ".join(path), block, path))
            inspect_sections(section.children, path)

    inspect_sections(ir.sections, [])
    for block in ir.blocks:
        if block.kind in {"chart", "diagram"}:
            unsupported.append(f"{block.kind} block {block.id}")
        elif block.kind == "table":
            tables.append(("Document", block, []))
        elif block.kind == "formula":
            formulas.append(("Document", block, []))
    if unsupported:
        raise UnsupportedIRContentError(
            "XLSX writer cannot represent source element(s): " + ", ".join(unsupported) + "."
        )
    for _, block, _ in tables:
        _validate_table(block)
    _validate_source_placements(tables, formulas)

    table_names: dict[str, str] = {}
    writer_warnings: list[str] = []
    table_number = 0
    for section_path, block, _ in tables:
        assert block.table is not None  # IR validation is guarded by _validated_ir.
        table_number += 1
        _validate_table(block)
        original_sheet_name = block.source.sheet_name
        if original_sheet_name:
            worksheet = _source_sheet(workbook, source_sheet_map, original_sheet_name)
            table_names[block.id] = worksheet.title
            min_col, min_row = _table_anchor(block.source, len(block.table.headers), len(block.table.rows))
            _write_table(worksheet, block, min_row, min_col, table_number, writer_warnings)
        else:
            worksheet = _new_sheet(workbook, f"Table {table_number}")
            table_names[block.id] = worksheet.title
            title_row = 1
            if block.table.caption:
                _write_text(worksheet.cell(title_row, 1), block.table.caption)
                worksheet.cell(title_row, 1).font = Font(bold=True, size=14)
                title_row += 1
            _write_table(worksheet, block, title_row, 1, table_number, writer_warnings)
        writer_warnings.append(
            f"Table {block.id} from {section_path} is stored on worksheet {worksheet.title}."
        )

    # Formula blocks keep their original cell coordinates when the source identifies
    # a sheet and cell. Unsafe/unanchored expressions remain visible as text.
    formula_sheets: dict[str, str] = {}
    for section_path, block, _ in formulas:
        formula = block.text
        original_sheet_name = block.source.sheet_name
        coordinate = _single_cell_coordinate(block.source.cell_range)
        if original_sheet_name and coordinate:
            worksheet = _source_sheet(workbook, source_sheet_map, original_sheet_name)
            formula_sheets[block.id] = worksheet.title
            cell = worksheet[coordinate]
            if _is_safe_excel_formula(formula):
                cell.value = formula
                cell.number_format = "General"
                cell.comment = None
            else:
                _write_text(cell, formula)
                writer_warnings.append(
                    f"Formula block {block.id} was preserved as text because its expression is invalid or outside the safe formula policy."
                )
        else:
            writer_warnings.append(
                f"Formula block {block.id} from {section_path} has no exact source sheet/cell; its expression is retained as text in IR Content."
            )

    document_sheet = _new_sheet(workbook, "Document")
    _write_key_values(document_sheet, [
        ("Document title", ir.title),
        ("Filename", ir.filename),
        ("Document ID", ir.document_id),
        ("Source format", ir.source_format.value),
        ("IR schema version", ir.schema_version),
        ("Metadata", _json(ir.metadata)),
        ("Extraction warnings", _json(ir.warnings)),
        ("Writer notes", _json(writer_warnings)),
    ])

    content_sheet = _new_sheet(workbook, "IR Content")
    _write_rows(content_sheet, [
        "Section path", "Section ID", "Block ID", "Kind", "Content", "Table worksheet", "Source location", "Attributes"
    ])
    for section in ir.sections:
        _write_section_content(content_sheet, section, [], table_names, formula_sheets)
    for block in ir.blocks:
        _write_block_content(content_sheet, "Document", "", block, table_names, formula_sheets)
    content_sheet.freeze_panes = "A2"
    content_sheet.auto_filter.ref = content_sheet.dimensions

    entities_sheet = _new_sheet(workbook, "Entities")
    _write_rows(entities_sheet, ["Entity ID", "Name", "Type", "Attributes", "Source locations"])
    for entity in ir.entities:
        _write_rows(entities_sheet, [
            entity.id, entity.name, entity.entity_type, _json(entity.attributes),
            _json([item.model_dump(mode="json", exclude_none=True) for item in entity.source_locations]),
        ])
    _finish_tabular_sheet(entities_sheet)

    facts_sheet = _new_sheet(workbook, "Facts")
    _write_rows(facts_sheet, ["Collection", "Fact ID", "Kind", "Subject", "Predicate", "Value", "Confidence", "Source locations"])
    for collection_name, facts in (("facts", ir.facts), ("metrics", ir.metrics), ("claims", ir.claims)):
        for fact in facts:
            _write_rows(facts_sheet, [
                collection_name, fact.id, fact.kind, fact.subject, fact.predicate, _json(fact.value), fact.confidence,
                _json([item.model_dump(mode="json", exclude_none=True) for item in fact.source_locations]),
            ])
    _finish_tabular_sheet(facts_sheet)

    relationships_sheet = _new_sheet(workbook, "Relationships")
    _write_rows(relationships_sheet, ["Source entity ID", "Target entity ID", "Relationship type", "Source locations"])
    for relationship in ir.relationships:
        _write_rows(relationships_sheet, [
            relationship.source_entity_id, relationship.target_entity_id, relationship.relationship_type,
            _json([item.model_dump(mode="json", exclude_none=True) for item in relationship.source_locations]),
        ])
    _finish_tabular_sheet(relationships_sheet)

    assets_sheet = _new_sheet(workbook, "Assets")
    _write_rows(assets_sheet, ["Source part", "Media type", "Size bytes"])
    for asset in ir.assets:
        _write_rows(assets_sheet, [asset.source_part, asset.media_type, asset.size_bytes])
    _finish_tabular_sheet(assets_sheet)

    provenance_sheet = _new_sheet(workbook, "Provenance")
    _write_rows(provenance_sheet, ["Extractor", "Extracted at", "Source format", "Details"])
    for provenance in ir.provenance:
        _write_rows(provenance_sheet, [
            provenance.extractor, provenance.extracted_at, provenance.source_format.value, _json(provenance.details),
        ])
    _finish_tabular_sheet(provenance_sheet)

    for worksheet in workbook.worksheets:
        _fit_columns(worksheet)
    workbook.calculation.fullCalcOnLoad = True
    workbook.calculation.forceFullCalc = True
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def validate_xlsx_output(content: bytes) -> None:
    if not content:
        raise ValueError("The XLSX renderer produced an empty file.")
    try:
        workbook = load_workbook(BytesIO(content), read_only=False, data_only=False, keep_links=False)
    except Exception as exc:
        raise ValueError("The rendered XLSX is not a valid workbook.") from exc
    try:
        if not workbook.worksheets or not any(sheet.sheet_state == "visible" for sheet in workbook.worksheets):
            raise ValueError("The rendered XLSX must contain a visible worksheet.")
        if "Document" not in workbook.sheetnames:
            raise ValueError("The rendered XLSX is missing its document metadata worksheet.")
        for worksheet in workbook.worksheets:
            if worksheet.max_row > 1_048_576 or worksheet.max_column > 16_384:
                raise ValueError("The rendered XLSX exceeds worksheet bounds.")
    finally:
        workbook.close()


def _validated_ir(document_ir: DocumentIR) -> DocumentIR:
    if isinstance(document_ir, DocumentIR):
        return DocumentIR.model_validate(document_ir.model_dump(mode="python"))
    return DocumentIR.model_validate(document_ir)


def _validate_table(block: IRBlock) -> None:
    table = block.table
    if table is None:
        raise UnsupportedIRContentError(f"Table block {block.id} has no table payload.")
    if not table.headers:
        raise UnsupportedIRContentError(f"Table block {block.id} has no header row.")
    if any(len(row) != len(table.headers) for row in table.rows):
        raise UnsupportedIRContentError(f"Table block {block.id} has rows that do not match its header width.")


def _source_sheet(workbook: Workbook, mapping: dict[str, Worksheet], original_name: str) -> Worksheet:
    existing = mapping.get(original_name)
    if existing is not None:
        return existing
    title = _safe_sheet_title(original_name)
    if title != original_name:
        raise UnsupportedIRContentError(
            f"Source worksheet name {original_name!r} cannot be preserved safely in an XLSX output."
        )
    worksheet = _new_sheet(workbook, title)
    mapping[original_name] = worksheet
    return worksheet


def _new_sheet(workbook: Workbook, desired: str) -> Worksheet:
    base = _safe_sheet_title(desired) or "Sheet"
    title = base
    index = 2
    while title.casefold() in {name.casefold() for name in workbook.sheetnames}:
        suffix = f" {index}"
        title = f"{base[:31 - len(suffix)]}{suffix}"
        index += 1
    return workbook.create_sheet(title)


def _safe_sheet_title(value: str) -> str:
    return re.sub(r"[\\/*?:\[\]]", "_", value).strip("'")[:31]


def _table_anchor(source: SourceLocation, header_count: int, row_count: int) -> tuple[int, int]:
    if not source.cell_range:
        return 1, 1
    try:
        min_col, min_row, max_col, max_row = range_boundaries(source.cell_range)
    except (TypeError, ValueError) as exc:
        raise UnsupportedIRContentError("A table source has an invalid cell range.") from exc
    if min_col is None or min_row is None or max_col is None or max_row is None:
        raise UnsupportedIRContentError("A table source has an incomplete cell range.")
    if max_col - min_col + 1 != header_count or max_row - min_row + 1 != row_count + 1:
        raise UnsupportedIRContentError("A table source range does not match its preserved rows and headers.")
    return min_row, min_col


def _validate_source_placements(tables, formulas) -> None:
    """Reject overlapping source placements before writing any cell data."""
    table_ranges: list[tuple[str, str, tuple[int, int, int, int]]] = []
    for _, block, _ in tables:
        source = block.source
        if not source.sheet_name:
            continue
        assert block.table is not None
        _table_anchor(source, len(block.table.headers), len(block.table.rows))
        if source.cell_range:
            try:
                min_col, min_row, max_col, max_row = range_boundaries(source.cell_range)
            except (TypeError, ValueError) as exc:
                raise UnsupportedIRContentError(f"Table block {block.id} has an invalid source range.") from exc
            if None in (min_col, min_row, max_col, max_row):
                raise UnsupportedIRContentError(f"Table block {block.id} has an incomplete source range.")
        else:
            assert block.table is not None
            min_row, min_col = 1, 1
            max_row = len(block.table.rows) + 1
            max_col = len(block.table.headers)
        current = (min_col, min_row, max_col, max_row)
        for other_id, other_sheet, other_range in table_ranges:
            if source.sheet_name.casefold() == other_sheet.casefold() and _ranges_overlap(current, other_range):
                raise UnsupportedIRContentError(
                    f"Table blocks {other_id} and {block.id} overlap on source worksheet {source.sheet_name!r}."
                )
        table_ranges.append((block.id, source.sheet_name, current))

    formula_cells: dict[tuple[str, str], str] = {}
    for _, block, _ in formulas:
        sheet_name = block.source.sheet_name
        coordinate = _single_cell_coordinate(block.source.cell_range)
        if not sheet_name or not coordinate:
            continue
        min_col, min_row, _, _ = range_boundaries(block.source.cell_range)
        for table_id, table_sheet, table_range in table_ranges:
            if sheet_name.casefold() == table_sheet.casefold() and _point_in_range(min_col, min_row, table_range):
                raise UnsupportedIRContentError(
                    f"Formula block {block.id} overlaps table block {table_id} at {sheet_name}!{coordinate}."
                )
        key = (sheet_name.casefold(), coordinate.upper())
        if key in formula_cells:
            raise UnsupportedIRContentError(
                f"Formula blocks {formula_cells[key]} and {block.id} overlap at {sheet_name}!{coordinate}."
            )
        formula_cells[key] = block.id


def _ranges_overlap(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> bool:
    left_min_col, left_min_row, left_max_col, left_max_row = left
    right_min_col, right_min_row, right_max_col, right_max_row = right
    return not (
        left_max_col < right_min_col or right_max_col < left_min_col
        or left_max_row < right_min_row or right_max_row < left_min_row
    )


def _point_in_range(column: int, row: int, bounds: tuple[int, int, int, int]) -> bool:
    min_col, min_row, max_col, max_row = bounds
    return min_col <= column <= max_col and min_row <= row <= max_row


def _write_table(
    worksheet: Worksheet,
    block: IRBlock,
    start_row: int,
    start_column: int,
    table_number: int,
    warnings: list[str],
) -> None:
    assert block.table is not None
    table = block.table
    header_row = start_row
    for column_offset, value in enumerate(table.headers):
        cell = worksheet.cell(header_row, start_column + column_offset)
        _write_excel_value(cell, value)
        cell.fill = _HEADER_FILL
        cell.font = Font(bold=True, color="202D48")
    for row_offset, row in enumerate(table.rows, start=1):
        for column_offset, value in enumerate(row):
            _write_excel_value(worksheet.cell(header_row + row_offset, start_column + column_offset), value)
    end_row = header_row + len(table.rows)
    end_column = start_column + len(table.headers) - 1
    worksheet.freeze_panes = worksheet.cell(header_row + 1, start_column).coordinate
    worksheet.auto_filter.ref = f"{get_column_letter(start_column)}{header_row}:{get_column_letter(end_column)}{end_row}"
    header_strings = [str(value) if value is not None else "" for value in table.headers]
    if table.rows and all(header_strings) and len({name.casefold() for name in header_strings}) == len(header_strings):
        display_name = f"IRTable{table_number}"
        excel_table = Table(
            displayName=display_name,
            ref=worksheet.auto_filter.ref,
        )
        excel_table.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium2", showFirstColumn=False, showLastColumn=False,
            showRowStripes=True, showColumnStripes=False,
        )
        worksheet.add_table(excel_table)
    elif table.rows:
        warnings.append(
            f"Table block {block.id} has blank or duplicate headings; its cells and autofilter are preserved without a structured Excel table object."
        )
    worksheet.sheet_view.showGridLines = True


def _write_section_content(
    worksheet: Worksheet,
    section: IRSection,
    parent_path: list[str],
    table_names: dict[str, str],
    formula_sheets: dict[str, str],
) -> None:
    path = [*parent_path, section.title]
    for block in section.blocks:
        _write_block_content(worksheet, " / ".join(path), section.id, block, table_names, formula_sheets)
    for child in section.children:
        _write_section_content(worksheet, child, path, table_names, formula_sheets)


def _write_block_content(
    worksheet: Worksheet,
    section_path: str,
    section_id: str,
    block: IRBlock,
    table_names: dict[str, str],
    formula_sheets: dict[str, str],
) -> None:
    text = block.text
    if block.kind == "table" and block.table is not None:
        text = block.table.caption or "Tabular source content"
    elif block.kind == "formula":
        text = block.text
    _write_rows(worksheet, [
        section_path,
        section_id,
        block.id,
        block.kind,
        text,
        table_names.get(block.id, formula_sheets.get(block.id, "")),
        _json(block.source.model_dump(mode="json", exclude_none=True)),
        _json(block.attributes),
    ])


def _write_key_values(worksheet: Worksheet, rows: list[tuple[str, Any]]) -> None:
    _write_rows(worksheet, ["Field", "Value"])
    worksheet["A1"].fill = _HEADER_FILL
    worksheet["B1"].fill = _HEADER_FILL
    worksheet["A1"].font = Font(bold=True)
    worksheet["B1"].font = Font(bold=True)
    for key, value in rows:
        _write_rows(worksheet, [key, value])
    worksheet.freeze_panes = "A2"


def _write_rows(worksheet: Worksheet, values: list[Any]) -> None:
    row = worksheet.max_row + 1 if worksheet.max_row > 1 or worksheet.cell(1, 1).value is not None else 1
    for column, value in enumerate(values, start=1):
        _write_excel_value(worksheet.cell(row, column), value)
    if row == 1:
        for cell in worksheet[row]:
            cell.fill = _HEADER_FILL
            cell.font = Font(bold=True, color="202D48")


def _write_excel_value(cell, value: Any) -> None:
    if isinstance(value, str):
        cell.value = value
        # Explicit string storage prevents formula injection from any source text.
        cell.data_type = "s"
    elif value is None or isinstance(value, (bool, int, float)):
        cell.value = value
    elif isinstance(value, datetime) and value.tzinfo is not None:
        _write_text(cell, value.isoformat())
    elif hasattr(value, "isoformat") and callable(value.isoformat):
        cell.value = value
    elif isinstance(value, (dict, list, tuple)):
        serialized = _json(value)
        cell.value = serialized
        cell.data_type = "s"
    else:
        raise UnsupportedIRContentError(f"XLSX writer cannot represent value type {type(value).__name__}.")
    cell.alignment = Alignment(vertical="top", wrap_text=True)


def _write_text(cell, value: str) -> None:
    cell.value = value
    cell.data_type = "s"


def _finish_tabular_sheet(worksheet: Worksheet) -> None:
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions
    for cell in worksheet[1]:
        cell.fill = _HEADER_FILL
        cell.font = Font(bold=True, color="202D48")


def _fit_columns(worksheet: Worksheet) -> None:
    for column in worksheet.columns:
        letter = get_column_letter(column[0].column)
        width = max((len(str(cell.value)) for cell in column if cell.value is not None), default=10)
        worksheet.column_dimensions[letter].width = max(12, min(width + 2, 60))


def _json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_default)
    except (TypeError, ValueError) as exc:
        raise UnsupportedIRContentError("XLSX writer encountered a value that cannot be serialized losslessly.") from exc


def _json_default(value: Any) -> str:
    if hasattr(value, "isoformat") and callable(value.isoformat):
        return value.isoformat()
    raise TypeError(f"Unsupported JSON value type: {type(value).__name__}")


def _single_cell_coordinate(value: str | None) -> str | None:
    if not value:
        return None
    try:
        min_col, min_row, max_col, max_row = range_boundaries(value)
    except (TypeError, ValueError):
        return None
    if None in (min_col, min_row, max_col, max_row) or min_col != max_col or min_row != max_row:
        return None
    return f"{get_column_letter(min_col)}{min_row}"


def _is_safe_excel_formula(formula: str) -> bool:
    if not formula.startswith("=") or len(formula) > 8192:
        return False
    if any(marker in formula for marker in ("[", "]", "|", "://")):
        return False
    try:
        tokens = Tokenizer(formula).items
    except Exception:
        return False
    for token in tokens:
        if token.type == "FUNC" and token.subtype == "OPEN":
            function = token.value[:-1].split(".")[-1].upper()
            if function in _FORBIDDEN_FORMULA_FUNCTIONS or function not in _SAFE_FUNCTIONS:
                return False
        if token.type == "OPERAND" and token.subtype == "RANGE":
            if any(marker in token.value for marker in ("[", "]", "|", "://")):
                return False
    return True
