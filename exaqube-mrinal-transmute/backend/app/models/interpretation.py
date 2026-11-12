"""Validated semantic interpretation models, separate from source DocumentIR."""

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr, model_validator

from app.models.documents import DocumentFormat
from app.models.intermediate import ProvenanceRecord, SourceLocation
from app.models.llm import LLMTokenUsage


EvidenceType = Literal["explicit", "inferred"]
Confidence = float
MetricValue = StrictInt | StrictFloat | StrictStr


class SourceReference(BaseModel):
    """A citation to an exact section or block in the original source IR."""

    model_config = ConfigDict(extra="forbid")

    block_id: str | None = None
    section_id: str | None = None
    source_location: SourceLocation

    @model_validator(mode="after")
    def require_ir_identifier(self) -> "SourceReference":
        if self.block_id is None and self.section_id is None:
            raise ValueError("A source reference must identify an IR block or section.")
        source = self.source_location
        if not any((
            source.slide_number is not None,
            source.sheet_name is not None,
            source.cell_range is not None,
            bool(source.section_path),
            source.paragraph_index is not None,
            source.element_index is not None,
            source.line_start is not None,
            source.line_end is not None,
            source.source_part is not None,
        )):
            raise ValueError("A source reference must include a concrete source location.")
        return self


class InterpretationFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str
    source_references: list[SourceReference] = Field(min_length=1)
    confidence: Confidence = Field(ge=0, le=1)
    evidence_type: EvidenceType


class InterpretationMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: MetricValue
    unit: str | None = None
    currency: str | None = None
    reporting_period: str | None = None
    description: str = ""
    source_references: list[SourceReference] = Field(min_length=1)
    confidence: Confidence = Field(ge=0, le=1)
    evidence_type: EvidenceType


class InterpretationEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: str = Field(min_length=1)
    name: str
    entity_type: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    source_references: list[SourceReference] = Field(min_length=1)
    confidence: Confidence = Field(ge=0, le=1)


class InterpretationClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str
    claim_type: str
    source_references: list[SourceReference] = Field(min_length=1)
    confidence: Confidence = Field(ge=0, le=1)
    evidence_type: EvidenceType


class InterpretationRelationship(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_entity_id: str
    target_entity_id: str
    relationship_type: str
    source_references: list[SourceReference] = Field(min_length=1)
    confidence: Confidence = Field(ge=0, le=1)


class InterpretationInsight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation: str
    reasoning: str
    supporting_source_references: list[SourceReference] = Field(min_length=1)
    confidence: Confidence = Field(ge=0, le=1)
    evidence_type: EvidenceType


class SemanticInterpretation(BaseModel):
    """Provider-produced semantic payload, without generated identity/provenance."""

    model_config = ConfigDict(extra="forbid")

    summary: str
    facts: list[InterpretationFact]
    metrics: list[InterpretationMetric]
    entities: list[InterpretationEntity]
    claims: list[InterpretationClaim]
    relationships: list[InterpretationRelationship]
    insights: list[InterpretationInsight]
    warnings: list[str]

    @model_validator(mode="after")
    def relationships_use_declared_entities(self) -> "SemanticInterpretation":
        entity_ids = {entity.entity_id for entity in self.entities}
        for relationship in self.relationships:
            if relationship.source_entity_id not in entity_ids or relationship.target_entity_id not in entity_ids:
                raise ValueError("Interpretation relationships must reference declared interpretation entities.")
        return self


class InterpretationProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    prompt_version: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_mock: bool
    source_provenance: list[ProvenanceRecord] = Field(min_length=1)
    token_usage: LLMTokenUsage | None = None


class InterpretationMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_format: DocumentFormat
    source_ir_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    instruction_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class DocumentInterpretation(BaseModel):
    """LLM interpretation stored independently from the immutable source IR."""

    model_config = ConfigDict(extra="forbid")

    interpretation_id: UUID
    document_id: str
    schema_version: str = "1.0"
    summary: str
    facts: list[InterpretationFact] = Field(default_factory=list)
    metrics: list[InterpretationMetric] = Field(default_factory=list)
    entities: list[InterpretationEntity] = Field(default_factory=list)
    claims: list[InterpretationClaim] = Field(default_factory=list)
    relationships: list[InterpretationRelationship] = Field(default_factory=list)
    insights: list[InterpretationInsight] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    provenance: InterpretationProvenance
    metadata: InterpretationMetadata
