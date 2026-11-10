"""Shared document and workflow domain types."""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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


class WorkflowNode(BaseModel):
    id: str
    source_format: DocumentFormat | None = None
    target_format: DocumentFormat
    instruction: str = ""


class WorkflowEdge(BaseModel):
    source: str
    target: str


class WorkflowDefinition(BaseModel):
    id: str
    name: str = "Untitled workflow"
    nodes: list[WorkflowNode] = Field(default_factory=list)
    edges: list[WorkflowEdge] = Field(default_factory=list)

