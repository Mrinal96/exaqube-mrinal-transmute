"""Extract sheets, table structure, cell values, and formula provenance."""

from io import BytesIO

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from app.models.intermediate import DocumentIR, Fact, SourceLocation, TableData
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
        for row in worksheet.iter_rows(min_row=1, max_row=max_row, min_col=1, max_col=max_column, values_only=False):
            matrix.append([cell.value for cell in row])
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
        if matrix:
            range_ref = f"A1:{get_column_letter(max_column)}{max_row}"
            headers = matrix[0]
            section.blocks.append(make_block(
                f"sheet-{sheet_order + 1}-cells", "table", source=SourceLocation(sheet_name=worksheet.title, cell_range=range_ref),
                table=TableData(headers=headers, rows=matrix[1:]),
                attributes={"table_names": table_names, "row_count": len(matrix), "column_count": max_column},
            ))
    workbook.close()
    if not ir.title:
        ir.title = next((section.title for section in ir.sections), filename)
    return ir
