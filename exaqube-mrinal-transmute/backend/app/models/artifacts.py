"""Validated target document content and persisted artifact metadata."""

from datetime import datetime, timezone
import math
from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, field_validator, model_validator

from app.models.documents import DocumentFormat
from app.models.interpretation import MetricValue, SourceReference

ARTIFACT_SCHEMA_VERSION = "1.2"


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


class PlannedArtifactText(ArtifactText):
    """HTML/DOCX content item with a plan identity; PPTX keeps its own element contract."""

    element_id: str | None = None
    element_type: Literal["paragraph", "list", "callout", "heading", "accordion"] | None = None
    label: str | None = None
    mapping_ids: list[str] = Field(default_factory=list)


class PlannedArtifactMetric(ArtifactMetric):
    element_id: str | None = None
    mapping_ids: list[str] = Field(default_factory=list)


class PlannedArtifactTable(ArtifactTable):
    element_id: str | None = None
    mapping_ids: list[str] = Field(default_factory=list)


class ArtifactSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heading: str = Field(min_length=1)
    paragraphs: list[ArtifactText] = Field(default_factory=list)
    bullet_points: list[ArtifactText] = Field(default_factory=list)
    metrics: list[ArtifactMetric] = Field(default_factory=list)
    tables: list[ArtifactTable] = Field(default_factory=list)


class HTMLArtifactSection(ArtifactSection):
    paragraphs: list[PlannedArtifactText] = Field(default_factory=list)
    bullet_points: list[PlannedArtifactText] = Field(default_factory=list)
    metrics: list[PlannedArtifactMetric] = Field(default_factory=list)
    tables: list[PlannedArtifactTable] = Field(default_factory=list)
    section_id: str | None = None
    semantic_element: Literal["main", "section", "article", "aside", "nav", "footer"] = "section"
    purpose: str | None = None
    mapping_ids: list[str] = Field(default_factory=list)
    component_order: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def section_has_content(self) -> "HTMLArtifactSection":
        if not (self.paragraphs or self.bullet_points or self.metrics or self.tables):
            raise ValueError("An HTML artifact section must contain source-backed content.")
        _validate_output_order(
            self.component_order,
            [item.element_id for item in (*self.paragraphs, *self.bullet_points, *self.metrics, *self.tables)],
            "HTML component",
        )
        return self


class HTMLArtifactContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_format: Literal["html"]
    page_title: str = Field(min_length=1)
    include_navigation: bool = True
    sections: list[HTMLArtifactSection] = Field(min_length=1)

    @model_validator(mode="after")
    def section_ids_are_unique(self) -> "HTMLArtifactContent":
        ids = [section.section_id for section in self.sections if section.section_id is not None]
        if len(ids) != len(set(ids)):
            raise ValueError("HTML artifact section IDs must be unique.")
        if sum(section.semantic_element == "main" for section in self.sections) > 1:
            raise ValueError("An HTML artifact may declare at most one main semantic section.")
        if any(section.semantic_element == "main" for section in self.sections) and len(self.sections) > 1:
            raise ValueError("A main semantic section must be the only top-level HTML artifact section.")
        return self


class DOCXArtifactSection(ArtifactSection):
    paragraphs: list[PlannedArtifactText] = Field(default_factory=list)
    bullet_points: list[PlannedArtifactText] = Field(default_factory=list)
    metrics: list[PlannedArtifactMetric] = Field(default_factory=list)
    tables: list[PlannedArtifactTable] = Field(default_factory=list)
    section_id: str | None = None
    heading_level: int = Field(default=1, ge=1, le=6)
    mapping_ids: list[str] = Field(default_factory=list)
    element_order: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_docx_element_order(self) -> "DOCXArtifactSection":
        _validate_output_order(
            self.element_order,
            [item.element_id for item in (*self.paragraphs, *self.bullet_points, *self.metrics, *self.tables)],
            "DOCX element",
        )
        return self


class DOCXArtifactContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_format: Literal["docx"]
    document_title: str = Field(min_length=1)
    sections: list[DOCXArtifactSection] = Field(min_length=1)

    @model_validator(mode="after")
    def section_ids_are_unique(self) -> "DOCXArtifactContent":
        ids = [section.section_id for section in self.sections if section.section_id is not None]
        if len(ids) != len(set(ids)):
            raise ValueError("DOCX artifact section IDs must be unique.")
        return self


def _validate_output_order(order: list[str], element_ids: list[str | None], label: str) -> None:
    if not order and not any(element_ids):
        return
    declared = [element_id for element_id in element_ids if element_id is not None]
    if len(declared) != len(set(declared)):
        raise ValueError(f"{label} IDs must be unique within their output section.")
    if len(order) != len(set(order)) or set(order) != set(declared):
        raise ValueError(f"{label} order must list every declared ID exactly once.")


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
