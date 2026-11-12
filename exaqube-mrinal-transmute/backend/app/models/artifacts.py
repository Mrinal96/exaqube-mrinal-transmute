"""Validated target document content and persisted artifact metadata."""

from datetime import datetime, timezone
import math
from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, field_validator, model_validator

from app.models.documents import DocumentFormat
from app.models.interpretation import MetricValue, SourceReference

ARTIFACT_SCHEMA_VERSION = "1.1"


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


class PPTXTitleElement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    element_id: str = Field(min_length=1)
    element_type: Literal["title"]
    mapping_ids: list[str] = Field(default_factory=list)
    content: ArtifactText


class PPTXParagraphElement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    element_id: str = Field(min_length=1)
    element_type: Literal["paragraph"]
    mapping_ids: list[str] = Field(default_factory=list)
    content: ArtifactText


class PPTXCalloutElement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    element_id: str = Field(min_length=1)
    element_type: Literal["callout"]
    mapping_ids: list[str] = Field(default_factory=list)
    content: ArtifactText


class PPTXBulletsElement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    element_id: str = Field(min_length=1)
    element_type: Literal["bullets"]
    mapping_ids: list[str] = Field(default_factory=list)
    items: list[ArtifactText] = Field(min_length=1)


class PPTXTableElement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    element_id: str = Field(min_length=1)
    element_type: Literal["table"]
    mapping_ids: list[str] = Field(default_factory=list)
    content: ArtifactTable


class PPTXMetricElement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    element_id: str = Field(min_length=1)
    element_type: Literal["metric"]
    mapping_ids: list[str] = Field(default_factory=list)
    content: ArtifactMetric


class PPTXChartSeries(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    values: list[StrictInt | StrictFloat | None] = Field(min_length=1)

    @field_validator("values")
    @classmethod
    def values_must_be_finite(cls, values: list[int | float | None]) -> list[int | float | None]:
        if any(isinstance(value, float) and not math.isfinite(value) for value in values):
            raise ValueError("Chart values must be finite numbers or null.")
        return values

    @model_validator(mode="after")
    def series_has_numeric_value(self) -> "PPTXChartSeries":
        if not self.name.strip():
            raise ValueError("A chart series name must not be blank.")
        if not any(value is not None for value in self.values):
            raise ValueError("A chart series must contain at least one numeric value.")
        return self


class PPTXChartContent(BaseModel):
    """Editable chart data and citations carried into the native PowerPoint chart."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    chart_type: Literal["bar", "line", "pie"]
    categories: list[str] = Field(min_length=1)
    series: list[PPTXChartSeries] = Field(min_length=1)
    source_references: list[SourceReference] = Field(min_length=1)

    @model_validator(mode="after")
    def chart_data_is_consistent(self) -> "PPTXChartContent":
        if not self.title.strip():
            raise ValueError("A chart title must not be blank.")
        if any(not category.strip() for category in self.categories):
            raise ValueError("Chart categories must not be blank.")
        if len(set(self.categories)) != len(self.categories):
            raise ValueError("Chart categories must be unique.")
        if any(len(item.values) != len(self.categories) for item in self.series):
            raise ValueError("Each chart series must have one value per category.")
        if self.chart_type == "pie":
            if len(self.series) != 1:
                raise ValueError("A pie chart must contain exactly one data series.")
            values = self.series[0].values
            if any(value is not None and value < 0 for value in values):
                raise ValueError("Pie chart values must not be negative.")
            if not any(value is not None and value > 0 for value in values):
                raise ValueError("A pie chart must contain at least one positive value.")
        return self


class PPTXChartElement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    element_id: str = Field(min_length=1)
    element_type: Literal["chart"]
    mapping_ids: list[str] = Field(default_factory=list)
    content: PPTXChartContent


PPTXArtifactElement = Annotated[
    Union[
        PPTXTitleElement,
        PPTXParagraphElement,
        PPTXCalloutElement,
        PPTXBulletsElement,
        PPTXTableElement,
        PPTXMetricElement,
        PPTXChartElement,
    ],
    Field(discriminator="element_type"),
]


class PPTXArtifactSlide(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slide_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    purpose: str | None = None
    visual_guidance: str | None = None
    title_source_references: list[SourceReference] = Field(default_factory=list)
    mapping_ids: list[str] = Field(default_factory=list)
    elements: list[PPTXArtifactElement] = Field(default_factory=list)


class PPTXArtifactContent(BaseModel):
    """Strict editable slide content; trusted provenance is added by the service."""

    model_config = ConfigDict(extra="forbid")

    target_format: Literal["pptx"]
    presentation_title: str = Field(min_length=1)
    slides: list[PPTXArtifactSlide] = Field(min_length=1)


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
    artifact_schema_version: str = ARTIFACT_SCHEMA_VERSION
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_mock: bool
    warnings: list[str] = Field(default_factory=list)
