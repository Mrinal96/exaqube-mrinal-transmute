"""Document-scoped transformation planning endpoints."""

from uuid import UUID, uuid4
import logging

from fastapi import APIRouter, Depends, Request, Response
from starlette.concurrency import run_in_threadpool

from app.api.document_resources import require_document
from app.api.operation_responses import usage_and_cost
from app.config import Settings, get_settings
from app.core.errors import APIError
from app.core.logging import log_context
from app.models.api import CostPricing, CreatePlanRequest, OperationRecord, PlanListResponse, PlanOperationResponse
from app.models.transformation import TransformationPlan
from app.services.container import get_planning_service
from app.services.planning import PlanningService
from app.storage.interpretations import InterpretationStore
from app.storage.operations import OperationStore
from app.storage.transformations import TransformationStore

router = APIRouter(prefix="/documents", tags=["plans"])
logger = logging.getLogger(__name__)


def _uuid(value: str, kind: str) -> str:
    try:
        parsed = UUID(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise APIError(400, f"invalid_{kind}_id", f"The {kind} ID is invalid.") from exc
    if str(parsed) != value.lower():
        raise APIError(400, f"invalid_{kind}_id", f"The {kind} ID is invalid.")
    return str(parsed)


@router.post("/{document_id}/interpretations/{interpretation_id}/plans", response_model=PlanOperationResponse, status_code=201)
async def create_plan(
    document_id: str,
    interpretation_id: str,
    body: CreatePlanRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    service: PlanningService = Depends(get_planning_service),
) -> PlanOperationResponse:
    document_id = _uuid(document_id, "document")
    interpretation_id = _uuid(interpretation_id, "interpretation")
    document_ir = require_document(settings.storage_root, document_id)
    interpretation = await run_in_threadpool(
        InterpretationStore(settings.storage_root).get_by_id, document_id, interpretation_id
    )
    if interpretation is None:
        raise APIError(404, "interpretation_not_found", "No interpretation matches this document and ID.")

    run_id = UUID(request.state.run_id) if request.state.run_id else uuid4()
    with log_context(request_id=request.state.request_id, run_id=str(run_id), document_id=document_id, operation="planning"):
        try:
            result = await service.create_plan_with_status(
                document_ir,
                interpretation,
                body.target_format,
                body.instructions,
                idempotency_key=body.idempotency_key,
            )
        except Exception as exc:
            logger.warning("planning_operation_failed", extra={"error_type": type(exc).__name__})
            try:
                _, failed_cost = usage_and_cost(settings, None)
                await run_in_threadpool(OperationStore(settings.storage_root).save, OperationRecord(
                    run_id=run_id,
                    request_id=request.state.request_id,
                    document_id=document_id,
                    operation="planning",
                    status="failed",
                    error_code="operation_failed",
                    usage=None,
                    cost=failed_cost,
                ))
            except Exception:
                logger.warning("planning_failure_record_write_failed")
            raise
        if result.reused:
            response.status_code = 200
        usage, cost = usage_and_cost(
            settings,
            None if result.plan.provenance.is_mock else result.plan.provenance.token_usage,
        )
        await run_in_threadpool(OperationStore(settings.storage_root).save, OperationRecord(
            run_id=run_id,
            request_id=request.state.request_id,
            document_id=document_id,
            operation="planning",
            status="done",
            result_id=result.plan.plan_id,
            usage=usage,
            cost=cost,
        ))
        return PlanOperationResponse(
            plan=result.plan,
            reused=result.reused,
            run_id=run_id,
            usage=usage,
            estimated_cost=cost.estimated_cost_usd,
            pricing=CostPricing(
                pricing_version=cost.pricing_version,
                input_cost_per_million_tokens=cost.input_cost_per_million_tokens,
                output_cost_per_million_tokens=cost.output_cost_per_million_tokens,
            ),
        )


@router.get("/{document_id}/interpretations/{interpretation_id}/plans", response_model=PlanListResponse)
async def list_interpretation_plans(
    document_id: str,
    interpretation_id: str,
    settings: Settings = Depends(get_settings),
) -> PlanListResponse:
    document_id = _uuid(document_id, "document")
    interpretation_id = _uuid(interpretation_id, "interpretation")
    require_document(settings.storage_root, document_id)
    interpretation = await run_in_threadpool(
        InterpretationStore(settings.storage_root).get_by_id, document_id, interpretation_id
    )
    if interpretation is None:
        raise APIError(404, "interpretation_not_found", "No interpretation matches this document and ID.")
    items = await run_in_threadpool(
        TransformationStore(settings.storage_root).list_for_interpretation, document_id, interpretation_id
    )
    return PlanListResponse(items=items, count=len(items))


@router.get("/{document_id}/plans", response_model=PlanListResponse)
async def list_document_plans(
    document_id: str,
    settings: Settings = Depends(get_settings),
) -> PlanListResponse:
    document_id = _uuid(document_id, "document")
    require_document(settings.storage_root, document_id)
    items = await run_in_threadpool(TransformationStore(settings.storage_root).list_for_document, document_id)
    return PlanListResponse(items=items, count=len(items))


@router.get("/{document_id}/plans/{plan_id}", response_model=TransformationPlan)
async def get_plan(
    document_id: str,
    plan_id: str,
    settings: Settings = Depends(get_settings),
) -> TransformationPlan:
    document_id = _uuid(document_id, "document")
    plan_id = _uuid(plan_id, "plan")
    require_document(settings.storage_root, document_id)
    record = await run_in_threadpool(TransformationStore(settings.storage_root).get_by_id, document_id, plan_id)
    if record is None:
        raise APIError(404, "plan_not_found", "No transformation plan matches this document and ID.")
    return record
