"""Canonical extraction IR shared by all source readers and future transforms."""

from datetime import datetime, timezone
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.documents import DocumentFormat


class SourceLocation(BaseModel):
    """Location in the original source, when a format exposes one."""

    model_config = ConfigDict(extra="forbid")
    slide_number: int | None = Field(default=None, ge=1)
    sheet_name: str | None = None
    cell_range: str | None = None
    section_path: list[str] = Field(default_factory=list)
    paragraph_index: int | None = Field(default=None, ge=0)
    element_index: int | None = Field(default=None, ge=0)
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    source_part: str | None = None

    @field_validator("cell_range")
    @classmethod
    def valid_a1_cell_range(cls, value: str | None) -> str | None:
        if value is not None and re.fullmatch(r"[A-Za-z]{1,3}[1-9][0-9]*(?::[A-Za-z]{1,3}[1-9][0-9]*)?", value) is None:
            raise ValueError("Source location cell_range must be an A1 cell or rectangular range.")
        return value

    @model_validator(mode="after")
    def validate_line_range(self) -> "SourceLocation":
        if self.line_start is not None and self.line_end is not None and self.line_end < self.line_start:
            raise ValueError("Source location line_end must be greater than or equal to line_start.")
        return self


class TableData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    headers: list[Any] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    caption: str | None = None


class IRBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    kind: Literal["text", "heading", "table", "list", "link", "formula", "diagram", "chart", "note"]
    text: str = ""
    level: int | None = None
    table: TableData | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    source: SourceLocation


class IRSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    level: int = Field(default=1, ge=1)
    order: int = Field(default=0, ge=0)
    blocks: list[IRBlock] = Field(default_factory=list)
    children: list["IRSection"] = Field(default_factory=list)
    source: SourceLocation | None = None


class Entity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    entity_type: str
    source_locations: list[SourceLocation] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)


class Fact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    kind: Literal["fact", "metric", "claim", "formula"]
    subject: str
    predicate: str
    value: Any
    confidence: float | None = Field(default=None, ge=0, le=1)
    source_locations: list[SourceLocation] = Field(default_factory=list)


class Relationship(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_entity_id: str
    target_entity_id: str
    relationship_type: str
    source_locations: list[SourceLocation] = Field(default_factory=list)


class AssetReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_part: str
    media_type: str | None = None
    size_bytes: int = Field(ge=0)


class ProvenanceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    extractor: str
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_format: DocumentFormat
    details: dict[str, Any] = Field(default_factory=dict)


class DocumentIR(BaseModel):
    """Loss-aware, format-neutral representation; it does not infer meaning via an LLM."""

    model_config = ConfigDict(extra="forbid")
    schema_version: str = "1.0"
    document_id: str
    source_format: DocumentFormat
    filename: str
    title: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    sections: list[IRSection] = Field(default_factory=list)
    blocks: list[IRBlock] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    metrics: list[Fact] = Field(default_factory=list)
    claims: list[Fact] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    assets: list[AssetReference] = Field(default_factory=list)
    provenance: list[ProvenanceRecord] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_document_references_and_ids(self) -> "DocumentIR":
        section_paths: dict[str, str] = {}
        block_paths: dict[str, str] = {}

        def register_section(section: IRSection, path: str) -> None:
            if not section.id.strip():
                raise ValueError(f"IR section at {path} has a blank ID.")
            if section.id in section_paths:
                raise ValueError(
                    f"Duplicate IR section ID {section.id!r} at {path}; first declared at {section_paths[section.id]}."
                )
            section_paths[section.id] = path
            for index, block in enumerate(section.blocks):
                register_block(block, f"{path}.blocks[{index}]")
            for index, child in enumerate(section.children):
                register_section(child, f"{path}.children[{index}]")

        def register_block(block: IRBlock, path: str) -> None:
            if not block.id.strip():
                raise ValueError(f"IR block at {path} has a blank ID.")
            if block.id in block_paths:
                raise ValueError(
                    f"Duplicate IR block ID {block.id!r} at {path}; first declared at {block_paths[block.id]}. "
                    "A block must appear once, either in a section or in the top-level blocks collection."
                )
            block_paths[block.id] = path

        for index, section in enumerate(self.sections):
            register_section(section, f"sections[{index}]")
        for index, block in enumerate(self.blocks):
            register_block(block, f"blocks[{index}]")

        entity_paths: dict[str, str] = {}
        for index, entity in enumerate(self.entities):
            path = f"entities[{index}]"
            if not entity.id.strip():
                raise ValueError(f"Entity at {path} has a blank ID.")
            if entity.id in entity_paths:
                raise ValueError(
                    f"Duplicate entity ID {entity.id!r} at {path}; first declared at {entity_paths[entity.id]}."
                )
            entity_paths[entity.id] = path
            _validate_reference_locations(entity.source_locations, path)

        fact_paths: dict[str, str] = {}
        for collection_name in ("facts", "metrics", "claims"):
            for index, fact in enumerate(getattr(self, collection_name)):
                path = f"{collection_name}[{index}]"
                if not fact.id.strip():
                    raise ValueError(f"Fact at {path} has a blank ID.")
                if fact.id in fact_paths:
                    raise ValueError(
                        f"Duplicate fact ID {fact.id!r} at {path}; first declared at {fact_paths[fact.id]}."
                    )
                fact_paths[fact.id] = path
                _validate_reference_locations(fact.source_locations, path)

        entity_ids = set(entity_paths)
        for index, relationship in enumerate(self.relationships):
            path = f"relationships[{index}]"
            missing = [
                entity_id for entity_id in (relationship.source_entity_id, relationship.target_entity_id)
                if entity_id not in entity_ids
            ]
            if missing:
                raise ValueError(
                    f"Relationship at {path} references unknown entity ID(s): {', '.join(repr(item) for item in missing)}."
                )
            _validate_reference_locations(relationship.source_locations, path)
        return self


def _validate_reference_locations(locations: list[SourceLocation], path: str) -> None:
    """Validate populated reference locations without requiring optional metadata to exist."""
    for index, location in enumerate(locations):
        if not any((
            location.slide_number is not None,
            location.sheet_name is not None,
            location.cell_range is not None,
            bool(location.section_path),
            location.paragraph_index is not None,
            location.element_index is not None,
            location.line_start is not None,
            location.line_end is not None,
            location.source_part is not None,
        )):
            raise ValueError(f"Source location at {path}.source_locations[{index}] contains no coordinates.")

