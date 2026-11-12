"""Typed transformation plans; plans describe outputs but never render them."""

from datetime import datetime, timezone
from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.documents import DocumentFormat
from app.models.interpretation import SourceReference
from app.models.llm import LLMTokenUsage


PlanSourceType = Literal["fact", "metric", "entity", "claim", "relationship", "insight", "ir_block"]
DOCX_PLAN_SCHEMA_VERSION = "2.0"
DestinationType = Literal[
    "slide", "slide_element", "worksheet", "table", "column",
    "doc_section", "doc_element", "diagram_node", "diagram_edge",
    "html_section", "html_component",
]


class PlanSourceItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_item_type: PlanSourceType
    source_item_id: str = Field(min_length=1)


class PlanDestination(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_type: DestinationType
    target_id: str = Field(min_length=1)


class ContentMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mapping_id: str = Field(min_length=1)
    source_item_type: PlanSourceType
    source_item_id: str = Field(min_length=1)
    destination: PlanDestination
    operation: Literal["preserve", "summarize", "reframe", "aggregate", "visualize", "reorganize"]
    formatting_guidance: str = ""
    source_references: list[SourceReference] = Field(min_length=1)


class OmittedContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_item_type: PlanSourceType
    source_item_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    source_references: list[SourceReference] = Field(min_length=1)

    @field_validator("reason")
    @classmethod
    def reason_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("An omission reason must not be blank.")
        return value


class PPTXElementPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    element_id: str = Field(min_length=1)
    element_type: Literal["title", "paragraph", "bullets", "table", "chart", "callout", "image_placeholder"]
    purpose: str
    mapping_ids: list[str] = Field(default_factory=list)


class PPTXSlidePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slide_id: str = Field(min_length=1)
    title: str
    purpose: str
    visual_guidance: str = ""
    mapping_ids: list[str] = Field(default_factory=list)
    elements: list[PPTXElementPlan] = Field(default_factory=list)


class PPTXOutputStructure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_format: Literal["pptx"]
    presentation_title: str
    slides: list[PPTXSlidePlan] = Field(min_length=1)


PPTX_PROVIDER_SCHEMA_VERSION = "2.0"


class PPTXPlanningElementDraft(BaseModel):
    """Provider-facing PPTX element outline; placement lives on ContentMapping."""

    model_config = ConfigDict(extra="forbid")

    element_id: str = Field(min_length=1)
    element_type: Literal["title", "paragraph", "bullets", "table", "chart", "callout", "image_placeholder"]
    purpose: str


class PPTXPlanningSlideDraft(BaseModel):
    """Provider-facing PPTX slide outline without duplicated mapping placement."""

    model_config = ConfigDict(extra="forbid")

    slide_id: str = Field(min_length=1)
    title: str
    purpose: str
    visual_guidance: str = ""
    elements: list[PPTXPlanningElementDraft] = Field(default_factory=list)


class PPTXPlanningOutputStructure(BaseModel):
    """LLM response structure; ContentMapping.destination is authoritative."""

    model_config = ConfigDict(extra="forbid")

    target_format: Literal["pptx"]
    presentation_title: str
    slides: list[PPTXPlanningSlideDraft] = Field(min_length=1)


class PPTXTransformationPlanDraft(BaseModel):
    """Provider response contract for PPTX planning before trusted materialization."""

    model_config = ConfigDict(extra="forbid")

    target_format: Literal["pptx"]
    output_structure: PPTXPlanningOutputStructure
    content_mappings: list[ContentMapping] = Field(default_factory=list)
    generation_instructions: list[str] = Field(min_length=1)
    preservation_rules: list[str] = Field(min_length=1)
    omissions: list[OmittedContent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def structure_matches_requested_format(self) -> "PPTXTransformationPlanDraft":
        if self.output_structure.target_format != self.target_format:
            raise ValueError("Output structure target format must match the requested target format.")
        return self


class XLSXColumnPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column_id: str = Field(min_length=1)
    name: str
    data_type: str
    purpose: str = ""
    mapping_ids: list[str] = Field(default_factory=list)


class XLSXTablePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table_id: str = Field(min_length=1)
    name: str
    purpose: str
    mapping_ids: list[str] = Field(default_factory=list)
    columns: list[XLSXColumnPlan] = Field(min_length=1)


class XLSXWorksheetPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worksheet_id: str = Field(min_length=1)
    name: str
    purpose: str
    mapping_ids: list[str] = Field(default_factory=list)
    tables: list[XLSXTablePlan] = Field(min_length=1)


class XLSXOutputStructure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_format: Literal["xlsx"]
    workbook_title: str
    worksheets: list[XLSXWorksheetPlan] = Field(min_length=1)


class DOCXElementPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    element_id: str = Field(min_length=1)
    element_type: Literal["heading", "paragraph", "table", "list", "callout"]
    purpose: str


class DOCXSectionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_id: str = Field(min_length=1)
    title: str
    heading_level: int = Field(ge=1, le=6)
    purpose: str
    elements: list[DOCXElementPlan] = Field(default_factory=list)


class DOCXOutputStructure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_format: Literal["docx"]
    document_title: str
    sections: list[DOCXSectionPlan] = Field(min_length=1)


class MermaidNodePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1)
    label: str
    role: str
    mapping_ids: list[str] = Field(default_factory=list)


class MermaidEdgePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edge_id: str = Field(min_length=1)
    source_node_id: str
    target_node_id: str
    label: str = ""
    mapping_ids: list[str] = Field(default_factory=list)


class MMDOutputStructure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_format: Literal["mmd"]
    diagram_type: str
    title: str
    nodes: list[MermaidNodePlan] = Field(min_length=1)
    relationships: list[MermaidEdgePlan] = Field(default_factory=list)

    @model_validator(mode="after")
    def edges_reference_existing_nodes(self) -> "MMDOutputStructure":
        node_ids = {node.node_id for node in self.nodes}
        if any(edge.source_node_id not in node_ids or edge.target_node_id not in node_ids for edge in self.relationships):
            raise ValueError("Mermaid relationships must reference declared output nodes.")
        return self


class HTMLComponentPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_id: str = Field(min_length=1)
    component_type: Literal["heading", "paragraph", "table", "list", "chart", "metric_card", "callout", "accordion", "link"]
    purpose: str
    mapping_ids: list[str] = Field(default_factory=list)


class HTMLSectionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_id: str = Field(min_length=1)
    heading: str
    semantic_element: Literal["main", "section", "article", "aside", "nav", "footer"] = "section"
    purpose: str
    mapping_ids: list[str] = Field(default_factory=list)
    components: list[HTMLComponentPlan] = Field(default_factory=list)


class HTMLOutputStructure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_format: Literal["html"]
    page_title: str
    include_navigation: bool = True
    sections: list[HTMLSectionPlan] = Field(min_length=1)


OutputStructure = Annotated[
    Union[PPTXOutputStructure, XLSXOutputStructure, DOCXOutputStructure, MMDOutputStructure, HTMLOutputStructure],
    Field(discriminator="target_format"),
]


class TransformationPlanDraft(BaseModel):
    """The validated provider response, before trusted metadata is attached."""

    model_config = ConfigDict(extra="forbid")

    target_format: DocumentFormat
    output_structure: OutputStructure
    content_mappings: list[ContentMapping] = Field(default_factory=list)
    generation_instructions: list[str] = Field(min_length=1)
    preservation_rules: list[str] = Field(min_length=1)
    omissions: list[OmittedContent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def structure_matches_requested_format(self) -> "TransformationPlanDraft":
        if self.output_structure.target_format != self.target_format.value:
            raise ValueError("Output structure target format must match the requested target format.")
        return self


class DOCXTransformationPlanDraft(BaseModel):
    """DOCX provider response; each content mapping owns its destination."""

    model_config = ConfigDict(extra="forbid")

    target_format: Literal["docx"]
    output_structure: DOCXOutputStructure
    content_mappings: list[ContentMapping] = Field(default_factory=list)
    generation_instructions: list[str] = Field(min_length=1)
    preservation_rules: list[str] = Field(min_length=1)
    omissions: list[OmittedContent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def structure_matches_requested_format(self) -> "DOCXTransformationPlanDraft":
        if self.output_structure.target_format != self.target_format:
            raise ValueError("Output structure target format must match the requested target format.")
        return self


class PlanValidationRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    validation_status: Literal["ready", "not_evaluated"]
    target_format: DocumentFormat
    required_content_items: list[PlanSourceItem] = Field(default_factory=list)
    require_source_reference_integrity: bool = True
    require_material_content_accounting: bool = True
    require_omission_reasons: bool = True
    require_target_structure_validation: bool = True


class TransformationProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    prompt_version: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_mock: bool
    token_usage: LLMTokenUsage | None = None


class TransformationMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_ir_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    interpretation_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    instruction_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class TransformationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: UUID
    document_id: str
    interpretation_id: UUID
    schema_version: str = "1.0"
    target_format: DocumentFormat
    user_instructions: str | None = None
    output_structure: OutputStructure | None = None
    content_mappings: list[ContentMapping] = Field(default_factory=list)
    generation_instructions: list[str] = Field(default_factory=list)
    preservation_rules: list[str] = Field(default_factory=list)
    omissions: list[OmittedContent] = Field(default_factory=list)
    validation_rules: PlanValidationRules
    provenance: TransformationProvenance
    metadata: TransformationMetadata
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_mock_and_format_contract(self) -> "TransformationPlan":
        if self.output_structure is not None and self.output_structure.target_format != self.target_format.value:
            raise ValueError("Output structure target format must match the plan target format.")
        if self.provenance.is_mock:
            if self.output_structure is not None or self.content_mappings or self.omissions:
                raise ValueError("Mock plans must not contain synthetic output structures or content mappings.")
            if self.generation_instructions or self.preservation_rules:
                raise ValueError("Mock plans must not contain synthetic generation instructions or preservation rules.")
            if self.validation_rules.validation_status != "not_evaluated":
                raise ValueError("Mock plan validation must be marked not_evaluated.")
        elif self.output_structure is None:
            raise ValueError("A real transformation plan requires an output structure.")
        return self
