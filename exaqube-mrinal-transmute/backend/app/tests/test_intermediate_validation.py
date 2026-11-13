"""Regression coverage for canonical IR identity and reference integrity."""

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
)


def _ir(**overrides):
    values = {
        "document_id": "doc-1",
        "source_format": DocumentFormat.HTML,
        "filename": "source.html",
        "sections": [],
        "blocks": [],
        "entities": [],
        "facts": [],
        "metrics": [],
        "claims": [],
        "relationships": [],
        "provenance": [ProvenanceRecord(extractor="test", source_format=DocumentFormat.HTML)],
    }
    values.update(overrides)
    return DocumentIR(**values)


def test_duplicate_nested_section_ids_report_both_locations():
    with pytest.raises(ValidationError, match=r"Duplicate IR section ID 'same' at sections\[1\]; first declared at sections\[0\]"):
        _ir(sections=[IRSection(id="same", title="A"), IRSection(id="same", title="B")])


def test_duplicate_block_across_nested_and_root_collections_is_rejected():
    block = IRBlock(id="duplicate", kind="text", text="evidence", source=SourceLocation(line_start=1))
    with pytest.raises(ValidationError, match=r"Duplicate IR block ID 'duplicate'.*sections\[0\].*blocks\[0\]"):
        _ir(sections=[IRSection(id="s", title="S", blocks=[block])], blocks=[block])


def test_duplicate_block_ids_across_sections_are_rejected():
    first = IRBlock(id="same", kind="text", source=SourceLocation(line_start=1))
    second = IRBlock(id="same", kind="text", source=SourceLocation(line_start=2))
    with pytest.raises(ValidationError, match="Duplicate IR block ID 'same'"):
        _ir(sections=[IRSection(id="a", title="A", blocks=[first]), IRSection(id="b", title="B", blocks=[second])])


def test_semantic_ids_are_unique_across_fact_collections():
    first = Fact(id="same", kind="fact", subject="revenue", predicate="is", value=10)
    second = Fact(id="same", kind="metric", subject="revenue", predicate="is", value=10)
    with pytest.raises(ValidationError, match=r"Duplicate fact ID 'same' at metrics\[0\]; first declared at facts\[0\]"):
        _ir(facts=[first], metrics=[second])


def test_entity_ids_are_unique_and_report_both_paths():
    with pytest.raises(ValidationError, match=r"Duplicate entity ID 'same' at entities\[1\]; first declared at entities\[0\]"):
        _ir(entities=[
            Entity(id="same", name="A", entity_type="org"),
            Entity(id="same", name="B", entity_type="org"),
        ])


def test_relationship_endpoints_must_exist():
    with pytest.raises(ValidationError, match="unknown entity ID.*absent"):
        _ir(relationships=[Relationship(
            source_entity_id="absent", target_entity_id="absent", relationship_type="related"
        )])


def test_optional_locations_remain_optional_but_populated_locations_are_validated():
    _ir(entities=[Entity(id="entity", name="E", entity_type="org")])
    with pytest.raises(ValidationError, match="contains no coordinates"):
        _ir(entities=[Entity(
            id="entity", name="E", entity_type="org", source_locations=[SourceLocation()]
        )])


def test_source_location_rejects_invalid_coordinate_order_and_values():
    with pytest.raises(ValidationError, match="line_end"):
        SourceLocation(line_start=8, line_end=4)
    with pytest.raises(ValidationError):
        SourceLocation(slide_number=0)
    with pytest.raises(ValidationError, match="A1 cell or rectangular range"):
        SourceLocation(sheet_name="Metrics", cell_range="A0:B3")
