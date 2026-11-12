"""Deterministic canonical-IR to XLSX writer coverage."""

from io import BytesIO

import pytest
from openpyxl import load_workbook

from app.models.documents import DocumentFormat
from app.models.intermediate import (
    DocumentIR,
    Entity,
    Fact,
    IRBlock,
    IRSection,
    ProvenanceRecord,
    Relationship,
    SourceLocation,
    TableData,
)
from app.services.native_writer_errors import UnsupportedIRContentError
from app.services.xlsx_writer import render_xlsx, validate_xlsx_output


def _ir(*, sections=None, blocks=None, entities=None, facts=None, relationships=None) -> DocumentIR:
    return DocumentIR(
        document_id="00000000-0000-4000-8000-000000000901",
        source_format=DocumentFormat.XLSX,
        filename="quarterly.xlsx",
        title="Quarterly results",
        metadata={"owner": "Finance", "reporting_period": "FY2026"},
        sections=sections or [],
        blocks=blocks or [],
        entities=entities or [],
        facts=facts or [],
        relationships=relationships or [],
        provenance=[ProvenanceRecord(
            extractor="xlsx_reader",
            source_format=DocumentFormat.XLSX,
            details={"sheet_count": 1, "reviewed": True},
        )],
        warnings=["A source value was blank."],
    )


def test_xlsx_writer_preserves_sections_tables_formulas_entities_facts_and_provenance():
    location = SourceLocation(sheet_name="Metrics", cell_range="A1:B3")
    formula_location = SourceLocation(sheet_name="Metrics", cell_range="B3")
    source = _ir(
        sections=[IRSection(
            id="section-metrics",
            title="Metrics",
            source=SourceLocation(sheet_name="Metrics"),
            blocks=[
                IRBlock(
                    id="table-metrics",
                    kind="table",
                    table=TableData(
                        headers=["Metric", "Value"],
                        rows=[["Revenue", 10], ["Total", "=SUM(B2:B2)"]],
                        caption="Quarterly values",
                    ),
                    source=location,
                ),
                IRBlock(id="formula-total", kind="formula", text="=SUM(B2:B2)", source=formula_location),
                IRBlock(
                    id="block-notes",
                    kind="text",
                    text="=HYPERLINK(\"https://unsafe.invalid\",\"open\")",
                    source=SourceLocation(sheet_name="Metrics", cell_range="C1"),
                    attributes={"tag": "p"},
                ),
                IRBlock(
                    id="block-heading",
                    kind="heading",
                    text="Executive summary",
                    level=2,
                    source=SourceLocation(section_path=["Metrics"], paragraph_index=1),
                ),
                IRBlock(
                    id="block-list",
                    kind="list",
                    text="North\nSouth",
                    attributes={"items": ["North", "South"], "ordered": False},
                    source=SourceLocation(section_path=["Metrics"], element_index=2),
                ),
                IRBlock(
                    id="block-link",
                    kind="link",
                    text="Quarterly filing",
                    attributes={"href": "https://example.invalid/report"},
                    source=SourceLocation(section_path=["Metrics"], element_index=3),
                ),
                IRBlock(
                    id="block-note",
                    kind="note",
                    text="Prepared for review.",
                    source=SourceLocation(section_path=["Metrics"], element_index=4),
                ),
            ],
        )],
        entities=[Entity(
            id="entity-acme",
            name="Acme Ltd.",
            entity_type="organization",
            attributes={"region": "EMEA"},
            source_locations=[SourceLocation(sheet_name="Metrics", cell_range="A2")],
        )],
        facts=[Fact(
            id="fact-revenue",
            kind="metric",
            subject="Acme",
            predicate="Revenue",
            value=10,
            confidence=0.99,
            source_locations=[SourceLocation(sheet_name="Metrics", cell_range="B2")],
        )],
        relationships=[Relationship(
            source_entity_id="entity-acme",
            target_entity_id="entity-acme",
            relationship_type="reports",
            source_locations=[SourceLocation(sheet_name="Metrics", cell_range="A1:B3")],
        )],
    )

    output = render_xlsx(source)
    validate_xlsx_output(output)
    workbook = load_workbook(BytesIO(output), data_only=False)
    assert workbook["Metrics"]["B3"].value == "=SUM(B2:B2)"
    assert workbook["Metrics"]["B3"].data_type == "f"
    assert "IRTable1" in workbook["Metrics"].tables
    content_rows = {
        workbook["IR Content"].cell(row, 3).value: row
        for row in range(2, workbook["IR Content"].max_row + 1)
    }
    assert workbook["IR Content"].cell(content_rows["block-notes"], 5).value.startswith("=HYPERLINK")
    assert workbook["IR Content"].cell(content_rows["block-notes"], 5).data_type == "s"
    assert {"block-heading", "block-list", "block-link", "block-note"}.issubset(content_rows)
    assert workbook["IR Content"].cell(content_rows["block-link"], 8).value == '{"href":"https://example.invalid/report"}'
    assert workbook["Document"]["B2"].value == "Quarterly results"
    assert "FY2026" in workbook["Document"]["B7"].value
    assert workbook["Entities"]["B2"].value == "Acme Ltd."
    assert "entity-acme" in workbook["Relationships"]["A2"].value
    assert workbook["Provenance"]["A2"].value == "xlsx_reader"
    assert "A source value was blank." in workbook["Document"]["B8"].value
    assert workbook["Metrics"].freeze_panes == "A2"
    workbook.close()


def test_xlsx_writer_handles_empty_ir_as_valid_metadata_workbook():
    output = render_xlsx(_ir())
    validate_xlsx_output(output)
    workbook = load_workbook(BytesIO(output), data_only=False)
    assert "Document" in workbook.sheetnames
    assert workbook["IR Content"].max_row == 1
    workbook.close()


def test_xlsx_writer_preserves_unanchored_or_unsafe_formula_as_text_with_note():
    source = _ir(blocks=[IRBlock(
        id="unsafe-formula",
        kind="formula",
        text='=WEBSERVICE("https://unsafe.invalid")',
        source=SourceLocation(sheet_name="Raw", cell_range="A1"),
    )])
    output = render_xlsx(source)
    workbook = load_workbook(BytesIO(output), data_only=False)
    assert workbook["Raw"]["A1"].value == '=WEBSERVICE("https://unsafe.invalid")'
    assert workbook["Raw"]["A1"].data_type == "s"
    assert "preserved as text" in workbook["Document"]["B9"].value
    workbook.close()


@pytest.mark.parametrize(
    "block",
    [
        IRBlock(
            id="malformed-table",
            kind="table",
            table=TableData(headers=["A", "B"], rows=[[1]]),
            source=SourceLocation(),
        ),
        IRBlock(id="unsupported-diagram", kind="diagram", text="flowchart TD", source=SourceLocation()),
        IRBlock(id="unsupported-chart", kind="chart", source=SourceLocation()),
    ],
)
def test_xlsx_writer_rejects_malformed_or_unsupported_ir_blocks(block):
    source = _ir(blocks=[block])
    with pytest.raises(UnsupportedIRContentError):
        render_xlsx(source)


def test_xlsx_writer_rejects_source_sheet_names_that_cannot_be_preserved():
    source = _ir(sections=[IRSection(
        id="section-invalid-sheet",
        title="Raw",
        blocks=[IRBlock(
            id="table-invalid-sheet",
            kind="table",
            table=TableData(headers=["Value"], rows=[[1]]),
            source=SourceLocation(sheet_name="Raw/Source", cell_range="A1:A2"),
        )],
    )])
    with pytest.raises(UnsupportedIRContentError, match="worksheet name"):
        render_xlsx(source)


@pytest.mark.parametrize("formula", ["SUM(A1:A2)", "=SUM(", '=HYPERLINK("https://bad", "go")', "=1+1"])
def test_xlsx_writer_never_interprets_non_formula_text_as_a_formula(formula):
    source = _ir(blocks=[IRBlock(id="source-text", kind="text", text=formula, source=SourceLocation())])
    workbook = load_workbook(BytesIO(render_xlsx(source)), data_only=False)
    cell = workbook["IR Content"]["E2"]
    assert cell.value == formula
    assert cell.data_type == "s"
    workbook.close()
