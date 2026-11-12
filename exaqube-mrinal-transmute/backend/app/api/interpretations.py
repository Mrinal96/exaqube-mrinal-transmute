"""Document-scoped semantic interpretation endpoints."""

from uuid import UUID, uuid4
import logging

from fastapi import APIRouter, Depends, Request, Response
from starlette.concurrency import run_in_threadpool

from app.api.document_resources import require_document
from app.api.operation_responses import usage_and_cost
from app.config import Settings, get_settings
from app.core.errors import APIError
from app.core.logging import log_context
from app.models.api import (
    CreateInterpretationRequest,
    CostPricing,
    InterpretationListResponse,
    InterpretationOperationResponse,
    OperationRecord,
)
from app.models.interpretation import DocumentInterpretation
from app.services.container import get_interpretation_service
from app.services.interpretation import InterpretationService
from app.storage.interpretations import InterpretationStore
from app.storage.operations import OperationStore

router = APIRouter(prefix="/documents", tags=["interpretations"])
logger = logging.getLogger(__name__)


def _document_uuid(value: str) -> str:
    try:
        parsed = UUID(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise APIError(400, "invalid_document_id", "The document ID is invalid.") from exc
    if str(parsed) != value.lower():
        raise APIError(400, "invalid_document_id", "The document ID is invalid.")
    return str(parsed)


def _interpretation_uuid(value: str) -> str:
    try:
        parsed = UUID(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise APIError(400, "invalid_interpretation_id", "The interpretation ID is invalid.") from exc
    if str(parsed) != value.lower():
        raise APIError(400, "invalid_interpretation_id", "The interpretation ID is invalid.")
    return str(parsed)


@router.post("/{document_id}/interpretations", response_model=InterpretationOperationResponse, status_code=201)
async def create_interpretation(
    document_id: str,
    body: CreateInterpretationRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    service: InterpretationService = Depends(get_interpretation_service),
) -> InterpretationOperationResponse:
    document_id = _document_uuid(document_id)
    document_ir = require_document(settings.storage_root, document_id)
    run_id = UUID(request.state.run_id) if request.state.run_id else uuid4()
    with log_context(request_id=request.state.request_id, run_id=str(run_id), document_id=document_id, operation="interpretation"):
        try:
            result = await service.interpret_with_status(
                document_ir, body.instructions, idempotency_key=body.idempotency_key
            )
        except Exception as exc:
            failed_usage = getattr(exc, "operation_usage", None)
            usage_summary, failed_cost = usage_and_cost(settings, failed_usage)
            category = getattr(exc, "operation_error_category", None)
            if category is None:
                category = getattr(getattr(exc, "category", None), "value", "operation_failed")
            logger.error(
                "interpretation_operation_failed",
                extra={
                    "exception_class": type(exc).__name__,
                    "error_category": category,
                    "persistence_failed": bool(getattr(exc, "persistence_failed", False)),
                    "token_usage_present": failed_usage is not None,
                    "token_usage": (
                        {
                            "prompt_tokens": failed_usage.prompt_tokens,
                            "completion_tokens": failed_usage.completion_tokens,
                            "total_tokens": failed_usage.total_tokens,
                        }
                        if failed_usage is not None else None
                    ),
                },
            )
            try:
                await run_in_threadpool(OperationStore(settings.storage_root).save, OperationRecord(
                    run_id=run_id,
                    request_id=request.state.request_id,
                    document_id=document_id,
                    operation="interpretation",
                    status="failed",
                    error_code="operation_failed",
                    usage=usage_summary,
                    cost=failed_cost,
                ))
            except Exception as record_exc:
                logger.error(
                    "interpretation_failure_record_write_failed",
                    extra={
                        "exception_class": type(record_exc).__name__,
                        "error_category": "operation_record_persistence",
                        "persistence_failed": True,
                    },
                )
            raise
        if result.reused:
            response.status_code = 200
        usage, cost = usage_and_cost(
            settings,
            None if result.interpretation.provenance.is_mock else result.interpretation.provenance.token_usage,
        )
        request_id = request.state.request_id
        await run_in_threadpool(OperationStore(settings.storage_root).save, OperationRecord(
            run_id=run_id,
            request_id=request_id,
            document_id=document_id,
            operation="interpretation",
            status="done",
            result_id=result.interpretation.interpretation_id,
            usage=usage,
            cost=cost,
        ))
        return InterpretationOperationResponse(
            interpretation=result.interpretation,
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


@router.get("/{document_id}/interpretations", response_model=InterpretationListResponse)
async def list_interpretations(
    document_id: str,
    settings: Settings = Depends(get_settings),
) -> InterpretationListResponse:
    document_id = _document_uuid(document_id)
    require_document(settings.storage_root, document_id)
    items = await run_in_threadpool(InterpretationStore(settings.storage_root).list_for_document, document_id)
    return InterpretationListResponse(items=items, count=len(items))


@router.get("/{document_id}/interpretations/{interpretation_id}", response_model=DocumentInterpretation)
async def get_interpretation(
    document_id: str,
    interpretation_id: str,
    settings: Settings = Depends(get_settings),
) -> DocumentInterpretation:
    document_id = _document_uuid(document_id)
    interpretation_id = _interpretation_uuid(interpretation_id)
    require_document(settings.storage_root, document_id)
    record = await run_in_threadpool(
        InterpretationStore(settings.storage_root).get_by_id, document_id, interpretation_id
    )
    if record is None:
        raise APIError(404, "interpretation_not_found", "No interpretation matches this document and ID.")
    return record
