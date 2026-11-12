"""Canonical extraction IR shared by all source readers and future transforms."""

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.documents import DocumentFormat


class SourceLocation(BaseModel):
    """Location in the original source, when a format exposes one."""

    model_config = ConfigDict(extra="forbid")
    slide_number: int | None = None
    sheet_name: str | None = None
    cell_range: str | None = None
    section_path: list[str] = Field(default_factory=list)
    paragraph_index: int | None = None
    element_index: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    source_part: str | None = None


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

