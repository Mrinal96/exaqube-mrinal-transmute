"""Synchronous source-to-artifact transformation and download endpoints."""

from uuid import UUID, uuid4
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from app.api.document_resources import require_document
from app.api.operation_responses import usage_and_cost
from app.config import Settings, get_settings
from app.core.errors import APIError
from app.core.logging import log_context
from app.models.api import ArtifactOperationResponse, CostPricing, CreateArtifactRequest, OperationRecord
from app.models.documents import DocumentFormat
from app.services.artifact_transformation import (
    ArtifactTransformationService,
    InvalidArtifactContentError,
    UnsupportedArtifactFormatError,
)
from app.services.container import get_interpretation_service
from app.services.interpretation import InterpretationService
from app.storage.artifacts import ArtifactStore
from app.storage.interpretations import InterpretationStore
from app.storage.operations import OperationStore


router = APIRouter(prefix="/documents", tags=["transformations"])
logger = logging.getLogger(__name__)
SUPPORTED_RENDERERS = {DocumentFormat.HTML, DocumentFormat.DOCX}
MEDIA_TYPES = {
    DocumentFormat.HTML: "text/html; charset=utf-8",
    DocumentFormat.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _document_uuid(value: str) -> str:
    try:
        parsed = str(UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise APIError(400, "invalid_document_id", "The document ID is invalid.") from exc
    if parsed != value.lower():
        raise APIError(400, "invalid_document_id", "The document ID is invalid.")
    return parsed


@router.post("/{document_id}/transformations", response_model=ArtifactOperationResponse, status_code=201)
async def create_transformation(
    document_id: str,
    body: CreateArtifactRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
    interpretation_service: InterpretationService = Depends(get_interpretation_service),
) -> ArtifactOperationResponse:
    document_id = _document_uuid(document_id)
    if body.target_format not in SUPPORTED_RENDERERS:
        raise APIError(422, "target_renderer_unavailable", "A native renderer is currently available only for HTML and DOCX.")
    document_ir = require_document(settings.storage_root, document_id)
    store = InterpretationStore(settings.storage_root)
    if body.interpretation_id is not None:
        interpretation = await run_in_threadpool(
            store.get_by_id, document_id, str(body.interpretation_id)
        )
    else:
        available = await run_in_threadpool(store.list_for_document, document_id)
        interpretation = max(available, key=lambda item: item.provenance.created_at, default=None)
    if interpretation is None:
        raise APIError(409, "interpretation_required", "Create or select a stored interpretation before transforming this document.")

    run_id = UUID(request.state.run_id) if request.state.run_id else uuid4()
    service = ArtifactTransformationService(interpretation_service.llm_service, settings.storage_root)
    with log_context(
        request_id=request.state.request_id,
        run_id=str(run_id),
        document_id=document_id,
        operation="transformation",
    ):
        try:
            result = await service.transform(
                document_ir,
                interpretation,
                body.target_format,
                run_id=run_id,
                user_instructions=body.instructions,
            )
        except Exception as exc:
            usage = getattr(exc, "operation_usage", None)
            usage_summary, failed_cost = usage_and_cost(settings, usage)
            logger.error(
                "artifact_transformation_failed",
                extra={"exception_class": type(exc).__name__, "error_category": "transformation_failed"},
            )
            try:
                await run_in_threadpool(OperationStore(settings.storage_root).save, OperationRecord(
                    run_id=run_id,
                    request_id=request.state.request_id,
                    document_id=document_id,
                    operation="transformation",
                    status="failed",
                    error_code="transformation_failed",
                    usage=usage_summary,
                    cost=failed_cost,
                ))
            except Exception:
                logger.exception("artifact_operation_record_write_failed")
            if isinstance(exc, UnsupportedArtifactFormatError):
                raise APIError(422, "target_renderer_unavailable", "A native renderer is currently available only for HTML and DOCX.") from exc
            if isinstance(exc, InvalidArtifactContentError):
                raise APIError(502, "invalid_artifact_output", str(exc)) from exc
            raise

        usage, cost = usage_and_cost(settings, result.usage)
        await run_in_threadpool(OperationStore(settings.storage_root).save, OperationRecord(
            run_id=run_id,
            request_id=request.state.request_id,
            document_id=document_id,
            operation="transformation",
            status="done",
            result_id=result.metadata.output_id,
            usage=usage,
            cost=cost,
        ))
        return ArtifactOperationResponse(
            output=result.metadata,
            download_url=f"/api/documents/{document_id}/outputs/{result.metadata.output_id}/download",
            run_id=run_id,
            usage=usage,
            estimated_cost=cost.estimated_cost_usd,
            pricing=CostPricing(
                pricing_version=cost.pricing_version,
                input_cost_per_million_tokens=cost.input_cost_per_million_tokens,
                output_cost_per_million_tokens=cost.output_cost_per_million_tokens,
            ),
        )


@router.get("/{document_id}/outputs/{output_id}/download")
async def download_transformation(document_id: str, output_id: str, settings: Settings = Depends(get_settings)):
    try:
        document_id = _document_uuid(document_id)
        require_document(settings.storage_root, document_id)
        found = await run_in_threadpool(ArtifactStore(settings.storage_root).get, document_id, output_id)
    except ValueError as exc:
        raise APIError(400, "invalid_output_id", "The document or output ID is invalid.") from exc
    if found is None:
        raise APIError(404, "output_not_found", "No rendered output matches this document and ID.")
    metadata, path = found
    return FileResponse(
        path,
        media_type=MEDIA_TYPES[metadata.target_format],
        filename=metadata.filename,
    )
