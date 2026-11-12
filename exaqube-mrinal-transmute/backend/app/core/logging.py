"""Structured JSON logging with the fields reserved for workflow tracing."""

import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from typing import Any


_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_run_id: ContextVar[str | None] = ContextVar("run_id", default=None)
_node_id: ContextVar[str | None] = ContextVar("node_id", default=None)
_document_id: ContextVar[str | None] = ContextVar("document_id", default=None)
_operation: ContextVar[str | None] = ContextVar("operation", default=None)

_SAFE_DIAGNOSTIC_FIELDS = (
    "exception_class",
    "cause_exception_class",
    "error_category",
    "failure_phase",
    "failure_reason",
    "persistence_failed",
    "source_reference_failure_category",
    "pydantic_errors",
    "json_parsing_failed",
    "json_parsing_succeeded",
    "content_empty",
    "content_char_count",
    "contains_markdown_code_fence",
    "token_usage",
    "content_exists",
    "content_type",
    "reasoning_exists",
    "reasoning_content_exists",
    "refusal_exists",
    "tool_calls_exists",
    "finish_reason",
    "token_usage_present",
    "provider_usage_present",
    "typed_token_usage_available",
    "usage_extra_fields",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "request_body_bytes",
    "request_content_bytes",
    "request_prompt_characters",
    "estimated_prompt_tokens",
    "prompt_token_estimate_method",
    "request_message_count",
    "normalized_table_cell_count",
    "normalized_section_reference_count",
    "validation_category",
    "validation_path",
    "validation_reason",
    "http_status",
    "provider_error_code",
    "provider_error_type",
    "provider_error_message",
    "rate_limit_kind",
    "rate_limit_headers",
    "retry_after_seconds",
    "rate_limit_reset_seconds",
    "selected_retry_delay_seconds",
    "retryable",
    "attempt",
    "next_attempt",
    "max_attempts",
    "delay_seconds",
    "retry_stop_reason",
)


@contextmanager
def log_context(
    *, request_id: str | None = None, run_id: str | None = None,
    node_id: str | None = None, document_id: str | None = None, operation: str | None = None,
):
    tokens: list[tuple[ContextVar, Token]] = []
    for variable, value in (
        (_request_id, request_id),
        (_run_id, run_id),
        (_node_id, node_id),
        (_document_id, document_id),
        (_operation, operation),
    ):
        if value is not None:
            tokens.append((variable, variable.set(value)))
    try:
        yield
    finally:
        for variable, token in reversed(tokens):
            variable.reset(token)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "svc": "kiln",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
            "run_id": getattr(record, "run_id", None) or _run_id.get(),
            "node_id": getattr(record, "node_id", None) or _node_id.get() or _document_id.get(),
            "request_id": getattr(record, "request_id", None) or _request_id.get(),
            "document_id": getattr(record, "document_id", None) or _document_id.get(),
            "operation": getattr(record, "operation", None) or _operation.get(),
        }
        for field in _SAFE_DIAGNOSTIC_FIELDS:
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

