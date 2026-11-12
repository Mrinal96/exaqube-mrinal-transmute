"""Safe, centralized API error handling."""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.services.llm_client import LLMClientError, LLMErrorCategory, LLMTruncatedResponseError
from app.services.interpretation import InvalidInterpretationResponseError, UnresolvedSourceReferenceError
from app.services.planning import (
    DocumentInterpretationMismatchError,
    InvalidPlanResponseError,
    InvalidTargetFormatError,
    PlanValidationError,
)
from app.storage.idempotency import IdempotencyConflictError
from app.storage.transformations import IncompatibleStoredPlanError

logger = logging.getLogger(__name__)


class APIError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _error_payload(request: Request, code: str, message: str) -> dict[str, object]:
    return {"error": {"code": code, "message": message, "request_id": getattr(request.state, "request_id", None)}}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=_error_payload(request, exc.code, exc.message))

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_error_payload(request, "request_validation_error", "The request is missing or contains invalid fields."),
        )

    @app.exception_handler(IdempotencyConflictError)
    async def idempotency_conflict_handler(request: Request, exc: IdempotencyConflictError) -> JSONResponse:
        return JSONResponse(status_code=409, content=_error_payload(
            request, "idempotency_key_conflict", "The idempotency key is already bound to a different request."
        ))

    @app.exception_handler(IncompatibleStoredPlanError)
    async def incompatible_stored_plan_handler(request: Request, exc: IncompatibleStoredPlanError) -> JSONResponse:
        return JSONResponse(status_code=409, content=_error_payload(
            request,
            "incompatible_stored_plan",
            "A stored DOCX plan uses an older destination schema and cannot be interpreted by this API version.",
        ))

    @app.exception_handler(InvalidTargetFormatError)
    async def target_format_handler(request: Request, exc: InvalidTargetFormatError) -> JSONResponse:
        return JSONResponse(status_code=422, content=_error_payload(
            request, "unsupported_target_format", "Target format must be one of PPTX, XLSX, DOCX, MMD, or HTML."
        ))

    @app.exception_handler(DocumentInterpretationMismatchError)
    async def association_handler(request: Request, exc: DocumentInterpretationMismatchError) -> JSONResponse:
        return JSONResponse(status_code=409, content=_error_payload(
            request, "resource_association_conflict", "The interpretation does not match this document."
        ))

    @app.exception_handler(InvalidInterpretationResponseError)
    @app.exception_handler(UnresolvedSourceReferenceError)
    @app.exception_handler(InvalidPlanResponseError)
    @app.exception_handler(PlanValidationError)
    async def invalid_provider_output_handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=502, content=_error_payload(
            request, "invalid_provider_output", "The provider returned output that did not pass validation."
        ))

    @app.exception_handler(LLMClientError)
    async def llm_error_handler(request: Request, exc: LLMClientError) -> JSONResponse:
        if isinstance(exc, LLMTruncatedResponseError):
            status_code, code, message = (
                502,
                "llm_output_truncated",
                "The LLM provider truncated its response before completing the structured output.",
            )
        elif exc.category == LLMErrorCategory.TIMEOUT:
            status_code, code, message = 504, "llm_timeout", "The LLM provider request timed out."
        elif exc.category == LLMErrorCategory.CONFIGURATION:
            status_code, code, message = 503, "llm_unavailable", "The LLM provider is not configured."
        elif exc.category == LLMErrorCategory.INVALID_RESPONSE:
            status_code, code, message = 502, "llm_invalid_response", "The LLM provider returned an invalid response."
        elif exc.category == LLMErrorCategory.PROVIDER and exc.status_code is not None and exc.status_code < 500 and exc.status_code != 429:
            status_code, code, message = 502, "llm_provider_error", "The LLM provider could not complete the request."
        else:
            status_code, code, message = 503, "llm_unavailable", "The LLM provider is temporarily unavailable."
        return JSONResponse(status_code=status_code, content=_error_payload(request, code, message))

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        messages = {
            404: "The requested resource was not found.",
            405: "The requested method is not allowed.",
            413: "The request payload is too large.",
            415: "The request media type is not supported.",
        }
        message = str(exc.detail) if isinstance(exc.detail, str) else "The request could not be completed."
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(request, "http_error", messages.get(exc.status_code, message)),
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_api_error", extra={"request_id": getattr(request.state, "request_id", None)})
        return JSONResponse(
            status_code=500,
            content=_error_payload(request, "internal_error", "An unexpected server error occurred."),
        )

