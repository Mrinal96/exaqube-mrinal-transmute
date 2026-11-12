"""Extract sheets, table structure, cell values, and formula provenance."""

from io import BytesIO
from zipfile import ZipFile

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from app.models.intermediate import AssetReference, DocumentIR, Fact, SourceLocation, TableData
from app.readers.common import base_ir, make_block, make_section
from app.readers.errors import ExtractionLimitError

MAX_WORKBOOK_ROWS = 5_000


def read_xlsx(content: bytes, document_id: str, filename: str) -> DocumentIR:
    workbook = load_workbook(BytesIO(content), read_only=False, data_only=False, keep_links=False)
    row_extent = sum(sheet.max_row for sheet in workbook.worksheets)
    if row_extent > MAX_WORKBOOK_ROWS:
        raise ExtractionLimitError(f"Workbook uses {row_extent} rows across its sheets; the maximum is {MAX_WORKBOOK_ROWS}.")
    properties = workbook.properties
    ir = base_ir(
        document_id,
        filename,
        "xlsx",
        "xlsx_reader",
        title=properties.title or "",
        metadata={
            "sheet_names": workbook.sheetnames,
            "author": properties.creator or "",
            "subject": properties.subject or "",
            "row_limit": MAX_WORKBOOK_ROWS,
        },
    )
    formula_index = 0
    for sheet_order, worksheet in enumerate(workbook.worksheets):
        section = make_section(f"sheet-{sheet_order + 1}", worksheet.title, order=sheet_order, source=SourceLocation(sheet_name=worksheet.title))
        ir.sections.append(section)
        max_row = worksheet.max_row
        max_column = worksheet.max_column
        table_names = [table.displayName for table in worksheet.tables.values()]
        matrix: list[list[object]] = []
        headers: list[object] = []
        for row_number, row in enumerate(worksheet.iter_rows(min_row=1, max_row=max_row, min_col=1, max_col=max_column, values_only=False), start=1):
            matrix.append([cell.value for cell in row])
            if row_number == 1:
                headers = [cell.value for cell in row]
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    formula_index += 1
                    location = SourceLocation(sheet_name=worksheet.title, cell_range=cell.coordinate)
                    formula = cell.value
                    section.blocks.append(make_block(
                        f"formula-{formula_index}", "formula", formula, location,
                        attributes={"cell": cell.coordinate, "data_type": cell.data_type},
                    ))
                    ir.facts.append(Fact(
                        id=f"formula-fact-{formula_index}", kind="formula", subject=f"{worksheet.title}!{cell.coordinate}",
                        predicate="formula", value=formula, source_locations=[location],
                    ))
                elif row_number > 1 and isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool):
                    header = str(headers[cell.column - 1]).strip() if cell.column <= len(headers) and headers[cell.column - 1] is not None else ""
                    if header and any(term in header.lower() for term in ("metric", "value", "amount", "total", "count", "rate", "revenue", "cost", "sales", "growth", "budget", "score", "price", "volume", "quantity", "percent")):
                        location = SourceLocation(sheet_name=worksheet.title, cell_range=cell.coordinate)
                        ir.metrics.append(Fact(
                            id=f"metric-{worksheet.title}-{cell.coordinate}", kind="metric", subject=worksheet.title,
                            predicate=header, value=cell.value, source_locations=[location],
                        ))
        if matrix:
            range_ref = f"A1:{get_column_letter(max_column)}{max_row}"
            headers = matrix[0]
            section.blocks.append(make_block(
                f"sheet-{sheet_order + 1}-cells", "table", source=SourceLocation(sheet_name=worksheet.title, cell_range=range_ref),
                table=TableData(headers=headers, rows=matrix[1:]),
                attributes={"table_names": table_names, "row_count": len(matrix), "column_count": max_column},
            ))
    workbook.close()
    with ZipFile(BytesIO(content)) as archive:
        for part in archive.namelist():
            if part.startswith("xl/media/") and not part.endswith("/"):
                info = archive.getinfo(part)
                ir.assets.append(AssetReference(source_part=part, size_bytes=info.file_size))
    if ir.assets:
        ir.warnings.append("Embedded workbook media are referenced in the IR; image contents are not interpreted.")
    if not ir.title:
        ir.title = next((section.title for section in ir.sections), filename)
    return ir
