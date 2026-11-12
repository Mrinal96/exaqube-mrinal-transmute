"""Persisted workflow definitions and asynchronous DAG run endpoints."""

from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from starlette.concurrency import run_in_threadpool

from app.api.document_resources import require_document
from app.config import Settings, get_settings
from app.core.errors import APIError
from app.models.documents import (
    WorkflowDefinition,
    WorkflowDefinitionCreate,
    WorkflowNode,
    WorkflowRunRequest,
)
from app.models.workflow_execution import WorkflowEvent, WorkflowNodeResult, WorkflowRun, WorkflowRunList
from app.orchestration.dag import WorkflowValidationError, validate_dag
from app.orchestration.engine import WorkflowExecutor
from app.services.container import get_interpretation_service, get_planning_service
from app.services.interpretation import InterpretationService
from app.services.planning import PlanningService
from app.storage.workflows import WorkflowStore


router = APIRouter(prefix="/workflows", tags=["workflows"])


def _uuid(value: str, label: str) -> str:
    try:
        normalized = str(UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise APIError(400, f"invalid_{label}_id", f"The {label} ID is invalid.") from exc
    if normalized != value.lower():
        raise APIError(400, f"invalid_{label}_id", f"The {label} ID is invalid.")
    return normalized


@router.post("", response_model=WorkflowDefinition, status_code=201)
async def create_workflow(
    body: WorkflowDefinitionCreate,
    settings: Settings = Depends(get_settings),
) -> WorkflowDefinition:
    workflow_id = str(uuid4())
    workflow = WorkflowDefinition(
        id=workflow_id,
        name=body.name,
        nodes=body.nodes,
        edges=body.edges,
    )
    try:
        validate_dag(workflow, allow_unbound_sources=True)
        for node in workflow.nodes:
            if node.kind == "source" and node.document_id:
                source_ir = require_document(settings.storage_root, node.document_id)
                if node.source_format is not None and node.source_format != source_ir.source_format:
                    raise WorkflowValidationError("Source node format does not match the uploaded document.")
    except WorkflowValidationError as exc:
        raise APIError(422, "invalid_workflow", str(exc)) from exc
    await run_in_threadpool(WorkflowStore(settings.storage_root).save_definition, workflow)
    return workflow


@router.get("/{workflow_id}", response_model=WorkflowDefinition)
async def get_workflow(workflow_id: str, settings: Settings = Depends(get_settings)) -> WorkflowDefinition:
    workflow_id = _uuid(workflow_id, "workflow")
    workflow = await run_in_threadpool(WorkflowStore(settings.storage_root).get_definition, workflow_id)
    if workflow is None:
        raise APIError(404, "workflow_not_found", "No workflow matches this ID.")
    return workflow


@router.post("/{workflow_id}/runs", response_model=WorkflowRun, status_code=202)
async def start_workflow_run(
    workflow_id: str,
    body: WorkflowRunRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    interpretation_service: InterpretationService = Depends(get_interpretation_service),
    planning_service: PlanningService = Depends(get_planning_service),
) -> WorkflowRun:
    workflow_id = _uuid(workflow_id, "workflow")
    store = WorkflowStore(settings.storage_root)
    workflow = await run_in_threadpool(store.get_definition, workflow_id)
    if workflow is None:
        raise APIError(404, "workflow_not_found", "No workflow matches this ID.")

    nodes: list[WorkflowNode] = []
    try:
        for node in workflow.nodes:
            if node.kind == "source" and not node.document_id and body.document_id:
                node = node.model_copy(update={"document_id": body.document_id})
            if node.kind == "source":
                if not node.document_id:
                    raise WorkflowValidationError("Each source node requires document_id on the node or run request.")
                ir = require_document(settings.storage_root, node.document_id)
                if node.source_format is not None and node.source_format != ir.source_format:
                    raise WorkflowValidationError("Source node format does not match the uploaded document.")
            nodes.append(node)
        resolved = workflow.model_copy(update={"nodes": nodes})
        validate_dag(resolved)
    except WorkflowValidationError as exc:
        raise APIError(422, "invalid_workflow", str(exc)) from exc

    run_id = uuid4()
    node_results = {
        node.id: WorkflowNodeResult(
            node_id=node.id,
            kind=node.kind,
            dependencies=[edge.source for edge in resolved.edges if edge.target == node.id],
            document_id=node.document_id,
        )
        for node in resolved.nodes
    }
    run = WorkflowRun(
        run_id=run_id,
        workflow_id=UUID(workflow_id),
        request_id=request.state.request_id,
        node_results=node_results,
        events=[WorkflowEvent(
            sequence=1,
            event="run_queued",
            status="queued",
            message="Workflow run was queued.",
        )],
    )
    await run_in_threadpool(store.save_run, run)
    executor = WorkflowExecutor(settings.storage_root, interpretation_service, planning_service)
    background_tasks.add_task(executor.execute, resolved, run_id)
    response.headers["Location"] = f"{settings.api_prefix.rstrip('/')}/workflows/{workflow_id}/runs/{run_id}"
    return run


@router.get("/{workflow_id}/runs", response_model=WorkflowRunList)
async def list_workflow_runs(workflow_id: str, settings: Settings = Depends(get_settings)) -> WorkflowRunList:
    workflow_id = _uuid(workflow_id, "workflow")
    store = WorkflowStore(settings.storage_root)
    if await run_in_threadpool(store.get_definition, workflow_id) is None:
        raise APIError(404, "workflow_not_found", "No workflow matches this ID.")
    items = await run_in_threadpool(store.list_runs, workflow_id)
    return WorkflowRunList(items=items, count=len(items))


@router.get("/{workflow_id}/runs/{run_id}", response_model=WorkflowRun)
async def get_workflow_run(
    workflow_id: str,
    run_id: str,
    settings: Settings = Depends(get_settings),
) -> WorkflowRun:
    workflow_id = _uuid(workflow_id, "workflow")
    run_id = _uuid(run_id, "run")
    run = await run_in_threadpool(WorkflowStore(settings.storage_root).get_run, workflow_id, run_id)
    if run is None:
        raise APIError(404, "workflow_run_not_found", "No workflow run matches these IDs.")
    return run
