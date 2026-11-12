"""Persistent, topological workflow execution using the existing domain services."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from app.api.document_resources import require_document
from app.core.logging import log_context
from app.models.artifacts import ArtifactMetadata
from app.models.documents import DocumentFormat, WorkflowDefinition, WorkflowNode
from app.models.intermediate import DocumentIR
from app.models.interpretation import DocumentInterpretation
from app.models.llm import LLMTokenUsage
from app.models.transformation import TransformationPlan
from app.models.workflow_execution import WorkflowEvent, WorkflowOutputReference, WorkflowRun
from app.orchestration.dag import topological_order
from app.services.artifact_renderers import validate_rendered_output
from app.services.artifact_transformation import (
    ArtifactTransformationService,
    UnsupportedArtifactElementError,
    UnsupportedArtifactFormatError,
)
from app.services.artifact_contracts import ArtifactContractConfigurationError
from app.services.interpretation import InterpretationService
from app.services.llm_client import LLMProviderError
from app.services.planning import PlanningService
from app.storage.artifacts import ArtifactStore
from app.storage.interpretations import InterpretationStore
from app.storage.transformations import TransformationStore
from app.storage.workflows import WorkflowStore

logger = logging.getLogger(__name__)
WORKFLOW_INTERPRETATION_MAX_COMPLETION_TOKENS = 4096


@dataclass(frozen=True)
class NodeValue:
    document_ir: DocumentIR | None = None
    interpretation: DocumentInterpretation | None = None
    plan: TransformationPlan | None = None
    artifact: ArtifactMetadata | None = None
    usage: LLMTokenUsage | None = None


class WorkflowExecutor:
    def __init__(
        self,
        storage_root: Path,
        interpretation_service: InterpretationService,
        planning_service: PlanningService,
    ) -> None:
        self.storage_root = storage_root
        self.interpretation_service = interpretation_service
        self.planning_service = planning_service
        self.artifact_service = ArtifactTransformationService(
            interpretation_service.llm_service, storage_root
        )
        self.store = WorkflowStore(storage_root)

    async def execute(self, workflow: WorkflowDefinition, run_id: UUID) -> None:
        run = self.store.get_run(workflow.id, str(run_id))
        if run is None:
            return
        nodes = {node.id: node for node in workflow.nodes}
        order = topological_order(workflow)
        values: dict[str, NodeValue] = {}
        parents: dict[str, list[str]] = {node.id: [] for node in workflow.nodes}
        for edge in workflow.edges:
            parents[edge.target].append(edge.source)

        run.status = "running"
        run.started_at = datetime.now(timezone.utc)
        self._event(run, "run_started", "running", None, "Workflow execution started.")
        self._save(run)

        for node_id in order:
            node = nodes[node_id]
            result = run.node_results[node_id]
            dependencies = parents[node_id]
            if any(run.node_results[parent].status in {"failed", "blocked"} for parent in dependencies):
                result.status = "blocked"
                result.error_code = "dependency_failed"
                result.error_message = "A required upstream node did not complete."
                result.finished_at = datetime.now(timezone.utc)
                self._event(run, "node_blocked", "blocked", node_id, result.error_message)
                self._save(run)
                continue

            result.started_at = datetime.now(timezone.utc)
            try:
                with log_context(
                    run_id=str(run_id),
                    request_id=run.request_id,
                    document_id=self._node_document_id(node, dependencies, values),
                    node_id=node_id,
                    operation=f"workflow_{node.kind}",
                ):
                    value = await self._execute_node(node, dependencies, values, run)
                values[node_id] = value
                result.document_id = value.document_ir.document_id if value.document_ir else (
                    value.artifact.document_id if value.artifact else result.document_id
                )
                if value.interpretation:
                    result.interpretation_id = value.interpretation.interpretation_id
                if value.plan:
                    result.plan_id = value.plan.plan_id
                if value.usage is not None:
                    result.usage = value.usage
                if value.artifact:
                    result.output = value.artifact
                    result.download_url = self._download_url(value.artifact)
                    if node.kind == "output" and all(
                        item.output.output_id != value.artifact.output_id for item in run.final_outputs
                    ):
                        run.final_outputs.append(WorkflowOutputReference(
                            node_id=node.id,
                            output=value.artifact,
                            download_url=self._download_url(value.artifact),
                        ))
                result.status = "done"
                result.finished_at = datetime.now(timezone.utc)
                self._event(run, "node_completed", "done", node_id, f"{node.kind.title()} node completed.")
            except Exception as exc:
                result.status = "failed"
                result.error_code, result.error_message = self._safe_error(exc)
                result.finished_at = datetime.now(timezone.utc)
                logger.error(
                    "workflow_node_failed",
                    extra={
                        "request_id": run.request_id,
                        "run_id": str(run.run_id),
                        "node_id": node_id,
                        "error_category": result.error_code,
                        "exception_class": type(exc).__name__,
                    },
                )
                self._event(run, "node_failed", "failed", node_id, result.error_message)
            self._save(run)

        if any(item.status == "failed" for item in run.node_results.values()):
            run.status = "failed"
        elif any(item.status == "blocked" for item in run.node_results.values()):
            run.status = "failed"
        else:
            run.status = "done"
        run.finished_at = datetime.now(timezone.utc)
        self._event(run, "run_completed", run.status, None, f"Workflow run {run.status}.")
        self._save(run)

    async def _execute_node(
        self,
        node: WorkflowNode,
        dependencies: list[str],
        values: dict[str, NodeValue],
        run: WorkflowRun,
    ) -> NodeValue:
        incoming = [values[item] for item in dependencies]
        if node.kind == "source":
            result = run.node_results[node.id]
            result.status = "reading"
            self._event(run, "node_started", "reading", node.id, "Loading the stored source document and canonical IR.")
            self._save(run)
            if not node.document_id:
                raise ValueError("Source node document_id was not resolved.")
            ir = await asyncio.to_thread(require_document, self.storage_root, node.document_id)
            if node.source_format is not None and node.source_format != ir.source_format:
                raise ValueError("Source node format does not match the uploaded document.")
            return NodeValue(document_ir=ir)

        context = _merge_context(incoming)
        if node.kind == "interpretation":
            if context.document_ir is None:
                raise ValueError("Interpretation node has no source IR input.")
            result = run.node_results[node.id]
            result.status = "interpreting"
            self._event(run, "node_started", "interpreting", node.id, "Interpreting the source IR.")
            self._save(run)
            if node.interpretation_id:
                interpretation = await asyncio.to_thread(
                    InterpretationStore(self.storage_root).get_by_id,
                    context.document_ir.document_id,
                    str(node.interpretation_id),
                )
                if interpretation is None:
                    raise ValueError("The selected interpretation does not exist for this document.")
            else:
                interpretation = await self.interpretation_service.interpret(
                    context.document_ir,
                    node.instruction or None,
                    max_completion_tokens=WORKFLOW_INTERPRETATION_MAX_COMPLETION_TOKENS,
                )
            return NodeValue(context.document_ir, interpretation, usage=interpretation.provenance.token_usage)

        if node.kind == "planning":
            if context.document_ir is None or context.interpretation is None or node.target_format is None:
                raise ValueError("Planning node requires source IR, interpretation, and target_format.")
            result = run.node_results[node.id]
            result.status = "planning"
            self._event(run, "node_started", "planning", node.id, "Creating a transformation plan.")
            self._save(run)
            stored = await self.planning_service.create_plan_with_status(
                context.document_ir,
                context.interpretation,
                node.target_format,
                node.instruction or None,
            )
            return NodeValue(
                context.document_ir,
                context.interpretation,
                stored.plan,
                usage=stored.plan.provenance.token_usage,
            )

        if node.kind == "transformation":
            if context.document_ir is None or context.interpretation is None or node.target_format is None:
                raise ValueError("Transformation node requires source IR, interpretation, and target_format.")
            result = run.node_results[node.id]
            result.status = "rendering"
            self._event(run, "node_started", "rendering", node.id, "Generating and validating the native output file.")
            self._save(run)
            artifact = await self.artifact_service.transform(
                context.document_ir,
                context.interpretation,
                node.target_format,
                run_id=run.run_id,
                user_instructions=node.instruction or None,
                plan=context.plan,
            )
            return NodeValue(
                context.document_ir,
                context.interpretation,
                context.plan,
                artifact.metadata,
                artifact.usage,
            )

        if node.kind == "output":
            artifact = context.artifact
            if artifact is None:
                raise ValueError("Output node has no generated artifact input.")
            result = run.node_results[node.id]
            result.status = "validating"
            self._event(run, "node_started", "validating", node.id, "Rechecking the persisted output artifact.")
            self._save(run)
            found = await asyncio.to_thread(
                ArtifactStore(self.storage_root).get, artifact.document_id, str(artifact.output_id)
            )
            if found is None:
                raise ValueError("The upstream artifact is missing from persistent storage.")
            metadata, path = found
            await asyncio.to_thread(validate_rendered_output, path.read_bytes(), metadata.target_format.value)
            return context

        raise ValueError("Unsupported workflow node kind.")

    @staticmethod
    def _safe_error(exc: Exception) -> tuple[str, str]:
        if isinstance(exc, ArtifactContractConfigurationError):
            return "artifact_contract_unavailable", "Artifact generation is not configured for this target format."
        if isinstance(exc, UnsupportedArtifactFormatError):
            return "target_renderer_unavailable", "No native renderer is available for this target format."
        if isinstance(exc, UnsupportedArtifactElementError):
            return "unsupported_artifact_element", str(exc)
        if isinstance(exc, LLMProviderError):
            return "provider_error", "The configured model provider could not complete this node."
        if isinstance(exc, ValueError):
            message = str(exc)
            safe_messages = {
                "Source node document_id was not resolved.",
                "Source node format does not match the uploaded document.",
                "The selected interpretation does not exist for this document.",
                "Interpretation node has no source IR input.",
                "Planning node requires source IR, interpretation, and target_format.",
                "Transformation node requires source IR, interpretation, and target_format.",
                "Output node has no generated artifact input.",
                "The upstream artifact is missing from persistent storage.",
                "Unsupported workflow node kind.",
            }
            if message in safe_messages:
                return "invalid_node_input", message
        return "node_execution_failed", "The workflow node failed. See the server logs using the run ID for details."

    @staticmethod
    def _node_document_id(node: WorkflowNode, dependencies: list[str], values: dict[str, NodeValue]) -> str | None:
        if node.document_id:
            return node.document_id
        for dependency in dependencies:
            value = values.get(dependency)
            if value and value.document_ir:
                return value.document_ir.document_id
            if value and value.artifact:
                return value.artifact.document_id
        return None

    @staticmethod
    def _download_url(artifact: ArtifactMetadata) -> str:
        return f"/api/documents/{artifact.document_id}/outputs/{artifact.output_id}/download"

    @staticmethod
    def _event(run: WorkflowRun, event: str, status: str, node_id: str | None, message: str) -> None:
        run.events.append(WorkflowEvent(
            sequence=len(run.events) + 1,
            event=event,
            status=status,
            node_id=node_id,
            message=message,
        ))
        run.updated_at = datetime.now(timezone.utc)

    def _save(self, run: WorkflowRun) -> None:
        self.store.save_run(run)


def _merge_context(values: list[NodeValue]) -> NodeValue:
    merged = NodeValue()
    for value in values:
        merged = NodeValue(
            document_ir=merged.document_ir or value.document_ir,
            interpretation=merged.interpretation or value.interpretation,
            plan=merged.plan or value.plan,
            artifact=merged.artifact or value.artifact,
            usage=merged.usage or value.usage,
        )
    return merged
