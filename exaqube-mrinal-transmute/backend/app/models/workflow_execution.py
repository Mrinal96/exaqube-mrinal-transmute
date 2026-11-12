"""Persisted workflow execution state and event snapshots."""

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.artifacts import ArtifactMetadata
from app.models.documents import WorkflowNodeKind
from app.models.llm import LLMTokenUsage


RunStatus = Literal["queued", "running", "done", "failed", "cancelled"]
NodeStatus = Literal[
    "queued", "reading", "interpreting", "planning", "rendering", "validating",
    "done", "failed", "blocked",
]


class WorkflowNodeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    kind: WorkflowNodeKind
    status: NodeStatus = "queued"
    dependencies: list[str] = Field(default_factory=list)
    document_id: str | None = None
    interpretation_id: UUID | None = None
    plan_id: UUID | None = None
    output: ArtifactMetadata | None = None
    download_url: str | None = None
    usage: LLMTokenUsage | None = None
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class WorkflowEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    event: str
    status: str
    node_id: str | None = None
    message: str


class WorkflowOutputReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    output: ArtifactMetadata
    download_url: str


class WorkflowRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    workflow_id: UUID
    request_id: str
    status: RunStatus = "queued"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    node_results: dict[str, WorkflowNodeResult]
    final_outputs: list[WorkflowOutputReference] = Field(default_factory=list)
    events: list[WorkflowEvent] = Field(default_factory=list)


class WorkflowRunList(BaseModel):
    items: list[WorkflowRun]
    count: int
