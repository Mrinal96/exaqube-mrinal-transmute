"""Deterministic canonical-IR to Mermaid writer coverage."""

import pytest
from pydantic import ValidationError

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
from app.services.mmd_writer import render_mmd, validate_mmd_output


def _ir(**updates) -> DocumentIR:
    values = {
        "document_id": "00000000-0000-4000-8000-000000000902",
        "source_format": DocumentFormat.HTML,
        "filename": "overview.html",
        "title": "Financial results",
        "metadata": {"owner": "Finance"},
        "sections": [],
        "blocks": [],
        "entities": [],
        "facts": [],
        "relationships": [],
        "provenance": [ProvenanceRecord(
            extractor="html_reader",
            source_format=DocumentFormat.HTML,
            details={"encoding": "utf-8"},
        )],
        "warnings": ["One source link was remote."],
    }
    values.update(updates)
    return DocumentIR(**values)


def test_mmd_writer_preserves_sections_blocks_entities_relationships_and_provenance():
    source = _ir(
        sections=[IRSection(
            id="section-finance",
            title='Financial [results] "Q3"',
            level=1,
            order=0,
            source=SourceLocation(section_path=["Financial"]),
            blocks=[IRBlock(
                id="block-revenue",
                kind="text",
                text="Revenue was $10 & rising\nby quarter.",
                source=SourceLocation(section_path=["Financial"], element_index=1),
                attributes={"source_tag": "p"},
                ), IRBlock(
                    id="block-table",
                    kind="table",
                    table=TableData(
                        headers=["Quarter", "Revenue"], rows=[["Q3", 10]], caption="Reported table",
                    ),
                    source=SourceLocation(section_path=["Financial"], element_index=2),
                ), IRBlock(
                    id="block-list",
                    kind="list",
                    text="Q1\nQ2",
                    attributes={"items": ["Q1", "Q2"]},
                    source=SourceLocation(section_path=["Financial"], element_index=3),
                ), IRBlock(
                    id="block-link",
                    kind="link",
                    text="Filing",
                    attributes={"href": "https://example.invalid"},
                    source=SourceLocation(section_path=["Financial"], element_index=4),
                ), IRBlock(
                    id="block-note",
                    kind="note",
                    text="Review note",
                    source=SourceLocation(section_path=["Financial"], element_index=5),
                ), IRBlock(
                    id="block-heading",
                    kind="heading",
                    text="Details",
                    level=2,
                    source=SourceLocation(section_path=["Financial"], element_index=6),
                )],
            children=[IRSection(
                id="section-quarterly",
                title="Quarterly",
                source=SourceLocation(section_path=["Financial", "Quarterly"]),
                blocks=[IRBlock(
                    id="block-formula",
                    kind="formula",
                    text="=SUM(B2:B3)",
                    source=SourceLocation(sheet_name="Metrics", cell_range="B4"),
                )],
            )],
        )],
        entities=[
            Entity(id="entity-acme", name="Acme & Co", entity_type="organization", attributes={"region": "EU"}),
            Entity(id="entity-customer", name="Customer", entity_type="stakeholder"),
        ],
        facts=[Fact(
            id="fact-revenue", kind="metric", subject="Acme", predicate="Revenue", value=10,
            source_locations=[SourceLocation(section_path=["Financial"], element_index=1)],
        )],
        relationships=[Relationship(
            source_entity_id="entity-acme", target_entity_id="entity-customer", relationship_type="serves",
            source_locations=[SourceLocation(section_path=["Financial"])],
        )],
    )

    output = render_mmd(source)
    validate_mmd_output(output)
    text = output.decode("utf-8")
    assert text.startswith("flowchart TD\n")
    assert 'subgraph section_group_0["Financial #91;results#93; #quot;Q3#quot;"]' in text
    assert "section_group_1" in text
    assert "ir_block_0" in text
    assert all(item in text for item in ("block-table", "block-list", "block-link", "block-note", "block-heading"))
    assert "Revenue was $10 #38; rising#92;nby quarter." in text
    assert "entity-acme" in text and "entity-customer" in text
    assert 'entity_0 -->|"#123;#quot;source_locations#quot;:' in text
    assert "semantic_0" in text
    assert '%% Transmute document_id: "00000000-0000-4000-8000-000000000902"' in text
    assert '%% Transmute provenance: [{"details":{"encoding":"utf-8"}' in text
    assert "One source link was remote." in text


def test_mmd_writer_emits_valid_minimal_diagram_for_empty_content():
    output = render_mmd(_ir())
    validate_mmd_output(output)
    assert output.decode("utf-8").startswith("flowchart TD\n")
    assert "document_0" in output.decode("utf-8")


def test_mmd_writer_preserves_source_mermaid_diagram_without_reparsing():
    original = "flowchart LR\n  A[Start] --> B{Ready?}\n  B -->|yes| C[Done]\n"
    source = _ir(
        source_format=DocumentFormat.MMD,
        sections=[IRSection(
            id="diagram",
            title="Process",
            source=SourceLocation(line_start=1, line_end=3),
            blocks=[IRBlock(
                id="diagram-source",
                kind="diagram",
                text=original,
                source=SourceLocation(line_start=1, line_end=3),
                attributes={"diagram_type": "flowchart"},
            )],
        )],
    )

    output = render_mmd(source).decode("utf-8")
    assert output.startswith(original.rstrip())
    assert "B{Ready?}" in output
    assert "%% Transmute provenance:" in output


def test_mmd_writer_rejects_source_diagram_when_other_ir_content_would_be_omitted():
    source = _ir(
        source_format=DocumentFormat.MMD,
        sections=[IRSection(
            id="diagram",
            title="Process",
            blocks=[IRBlock(id="diagram-source", kind="diagram", text="flowchart TD\n A-->B", source=SourceLocation())],
        )],
        facts=[Fact(id="fact-1", kind="fact", subject="A", predicate="has", value="B")],
    )
    with pytest.raises(UnsupportedIRContentError, match="cannot merge"):
        render_mmd(source)


def test_mmd_writer_rejects_relationships_with_missing_entities():
    with pytest.raises(ValidationError, match="unknown entity ID"):
        _ir(relationships=[Relationship(
            source_entity_id="missing-source", target_entity_id="missing-target", relationship_type="depends_on",
        )])


def test_mmd_writer_rejects_unsupported_chart_blocks_instead_of_dropping_them():
    source = _ir(blocks=[IRBlock(id="chart-1", kind="chart", source=SourceLocation())])
    with pytest.raises(UnsupportedIRContentError, match="chart block"):
        render_mmd(source)


@pytest.mark.parametrize("content", [b"", b"not a diagram", b"flowchart\n"])
def test_mmd_validator_rejects_empty_or_malformed_source(content):
    with pytest.raises(ValueError):
        validate_mmd_output(content)


@pytest.mark.parametrize(
    "diagram, reason",
    [
        (b"A --> B\nflowchart TD", "declaration must precede"),
        (b"flowchart TD\nsubgraph one\nA-->B", "unclosed subgraph"),
        (b"flowchart TD\nend", "unmatched subgraph end"),
        (b"flowchart TD\nA\x00B", "control character"),
        (b"flowchart TD\nsequenceDiagram", "exactly one"),
    ],
)
def test_mmd_validator_rejects_known_structural_errors_without_claiming_full_grammar(diagram, reason):
    with pytest.raises(ValueError, match=reason):
        validate_mmd_output(diagram)
