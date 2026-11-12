"""Validated target document content and persisted artifact metadata."""

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.documents import DocumentFormat
from app.models.interpretation import MetricValue, SourceReference


class ArtifactText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    source_references: list[SourceReference] = Field(min_length=1)


class ArtifactMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    value: MetricValue
    unit: str | None = None
    currency: str | None = None
    reporting_period: str | None = None
    source_references: list[SourceReference] = Field(min_length=1)


class ArtifactTable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    caption: str = ""
    headers: list[str] = Field(min_length=1)
    rows: list[list[str]]
    source_references: list[SourceReference] = Field(min_length=1)

    @model_validator(mode="after")
    def rows_match_headers(self) -> "ArtifactTable":
        if any(len(row) != len(self.headers) for row in self.rows):
            raise ValueError("Artifact table rows must match the declared header width.")
        return self


class ArtifactSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heading: str = Field(min_length=1)
    paragraphs: list[ArtifactText] = Field(default_factory=list)
    bullet_points: list[ArtifactText] = Field(default_factory=list)
    metrics: list[ArtifactMetric] = Field(default_factory=list)
    tables: list[ArtifactTable] = Field(default_factory=list)


class HTMLArtifactSection(ArtifactSection):
    @model_validator(mode="after")
    def section_has_content(self) -> "HTMLArtifactSection":
        if not (self.paragraphs or self.bullet_points or self.metrics or self.tables):
            raise ValueError("An HTML artifact section must contain source-backed content.")
        return self


class HTMLArtifactContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_format: Literal["html"]
    page_title: str = Field(min_length=1)
    sections: list[HTMLArtifactSection] = Field(min_length=1)


class DOCXArtifactContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_format: Literal["docx"]
    document_title: str = Field(min_length=1)
    sections: list[ArtifactSection] = Field(min_length=1)


class ArtifactMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_id: UUID
    document_id: str
    interpretation_id: UUID
    target_format: DocumentFormat
    filename: str
    provider: str
    model: str
    prompt_version: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_mock: bool
    warnings: list[str] = Field(default_factory=list)
