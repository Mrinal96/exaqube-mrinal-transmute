"""Request, response, and operational metadata for M2.4 APIs."""

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.artifacts import ArtifactMetadata
from app.models.documents import DocumentFormat
from app.models.interpretation import DocumentInterpretation
from app.models.llm import LLMTokenUsage
from app.models.transformation import TransformationPlan


class CreateInterpretationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instructions: str | None = Field(default=None, max_length=8000)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class CreatePlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_format: DocumentFormat
    instructions: str | None = Field(default=None, max_length=8000)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class CreateArtifactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_format: DocumentFormat
    instructions: str | None = Field(default=None, max_length=8000)
    interpretation_id: UUID | None = None


class UsageSummary(BaseModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)

    @classmethod
    def from_llm_usage(cls, usage: LLMTokenUsage | None) -> "UsageSummary | None":
        if usage is None:
            return None
        return cls(
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
        )


class CostSummary(BaseModel):
    currency: Literal["USD"] = "USD"
    estimated_cost_usd: Decimal | None = None
    pricing_version: str | None = None
    input_cost_per_million_tokens: Decimal | None = None
    output_cost_per_million_tokens: Decimal | None = None


class CostPricing(BaseModel):
    currency: Literal["USD"] = "USD"
    pricing_version: str | None = None
    input_cost_per_million_tokens: Decimal | None = None
    output_cost_per_million_tokens: Decimal | None = None


class InterpretationOperationResponse(BaseModel):
    interpretation: DocumentInterpretation
    reused: bool
    run_id: UUID
    usage: UsageSummary | None
    estimated_cost: Decimal | None
    pricing: CostPricing


class PlanOperationResponse(BaseModel):
    plan: TransformationPlan
    reused: bool
    run_id: UUID
    usage: UsageSummary | None
    estimated_cost: Decimal | None
    pricing: CostPricing


class ArtifactOperationResponse(BaseModel):
    output: ArtifactMetadata
    download_url: str
    run_id: UUID
    usage: UsageSummary | None
    estimated_cost: Decimal | None
    pricing: CostPricing


class InterpretationListResponse(BaseModel):
    items: list[DocumentInterpretation]
    count: int


class PlanListResponse(BaseModel):
    items: list[TransformationPlan]
    count: int


class OperationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    request_id: str
    document_id: str
    operation: Literal["interpretation", "planning", "transformation"]
    status: Literal["done", "failed"]
    result_id: UUID | None = None
    error_code: str | None = None
    usage: UsageSummary | None = None
    cost: CostSummary
