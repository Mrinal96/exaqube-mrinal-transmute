"""Shared document and workflow domain types."""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DocumentFormat(StrEnum):
    PPTX = "pptx"
    XLSX = "xlsx"
    DOCX = "docx"
    MMD = "mmd"
    HTML = "html"


class DocumentMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    filename: str
    format: DocumentFormat
    size_bytes: int = Field(ge=0)
    sha256: str
    detected_mime: str
    uploaded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    extraction_status: Literal["complete"] = "complete"
    warnings: list[str] = Field(default_factory=list)


WorkflowNodeKind = Literal["source", "interpretation", "planning", "transformation", "output"]


class WorkflowNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    kind: WorkflowNodeKind = "transformation"
    source_format: DocumentFormat | None = None
    target_format: DocumentFormat | None = None
    document_id: str | None = None
    interpretation_id: UUID | None = None
    instruction: str = Field(default="", max_length=8000)

    @model_validator(mode="after")
    def target_format_matches_kind(self) -> "WorkflowNode":
        if self.kind in {"planning", "transformation"} and self.target_format is None:
            raise ValueError(f"A {self.kind} node requires target_format.")
        if self.kind not in {"planning", "transformation"} and self.target_format is not None:
            raise ValueError(f"A {self.kind} node cannot declare target_format.")
        if self.kind == "source" and self.interpretation_id is not None:
            raise ValueError("A source node cannot select an interpretation.")
        return self


class WorkflowEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    target: str


class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str = "Untitled workflow"
    nodes: list[WorkflowNode] = Field(default_factory=list)
    edges: list[WorkflowEdge] = Field(default_factory=list)


class WorkflowDefinitionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="Untitled workflow", min_length=1, max_length=200)
    nodes: list[WorkflowNode] = Field(min_length=1)
    edges: list[WorkflowEdge] = Field(default_factory=list)


class WorkflowRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str | None = None

