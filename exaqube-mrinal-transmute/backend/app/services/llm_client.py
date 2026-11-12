"""OpenAI-compatible chat-completions transport and explicit mock provider."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
import json
import math
import re
import time
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

import httpx
import logging
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from pydantic import ValidationError

from app.models.llm import LLMCompletionResult, LLMErrorCategory, LLMRequestMessage, LLMTokenUsage


logger = logging.getLogger(__name__)
_KNOWN_FINISH_REASONS = {"stop", "length", "tool_calls", "content_filter", "function_call"}
_TOKEN_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens")
_GROQ_USAGE_METADATA_FIELDS = {
    "queue_time",
    "prompt_time",
    "completion_time",
    "total_time",
    "prompt_tokens_details",
    "completion_tokens_details",
}
_RATE_LIMIT_HEADER_NAMES = (
    "retry-after",
    "x-ratelimit-limit-requests",
    "x-ratelimit-remaining-requests",
    "x-ratelimit-reset-requests",
    "x-ratelimit-limit-tokens",
    "x-ratelimit-remaining-tokens",
    "x-ratelimit-reset-tokens",
)


class LLMClientError(RuntimeError):
    """Safe internal error; deliberately excludes request and provider body data."""

    def __init__(
        self,
        category: LLMErrorCategory,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.status_code = status_code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


class LLMConfigurationError(LLMClientError):
    def __init__(self, message: str = "LLM configuration is incomplete or invalid.") -> None:
        super().__init__(LLMErrorCategory.CONFIGURATION, message)


class LLMTimeoutError(LLMClientError):
    def __init__(self) -> None:
        super().__init__(LLMErrorCategory.TIMEOUT, "The LLM provider request timed out.", retryable=True)


class LLMConnectionError(LLMClientError):
    def __init__(self) -> None:
        super().__init__(LLMErrorCategory.CONNECTION, "The LLM provider could not be reached.", retryable=True)


class LLMProviderError(LLMClientError):
    def __init__(
        self,
        status_code: int,
        retry_after_seconds: float | None = None,
        *,
        provider_error_code: str | None = None,
        provider_error_type: str | None = None,
        provider_error_message: str | None = None,
        rate_limit_kind: str | None = None,
        rate_limit_headers: dict[str, str] | None = None,
        rate_limit_reset_seconds: float | None = None,
        selected_retry_delay_seconds: float | None = None,
        retryable: bool | None = None,
    ) -> None:
        is_permanent_quota_error = rate_limit_kind == "quota"
        super().__init__(
            LLMErrorCategory.PROVIDER,
            f"The LLM provider returned HTTP {status_code}.",
            status_code=status_code,
            retryable=(status_code == 429 or status_code >= 500) if retryable is None else retryable,
            retry_after_seconds=retry_after_seconds,
        )
        self.provider_error_code = provider_error_code
        self.provider_error_type = provider_error_type
        self.provider_error_message = provider_error_message
        self.rate_limit_kind = rate_limit_kind
        self.rate_limit_headers = rate_limit_headers or {}
        self.rate_limit_reset_seconds = rate_limit_reset_seconds
        self.selected_retry_delay_seconds = selected_retry_delay_seconds
        if is_permanent_quota_error:
            self.retryable = False


class LLMInvalidResponseError(LLMClientError):
    def __init__(
        self,
        message: str = "The LLM provider returned an invalid response.",
        *,
        failure_phase: str = "response_validation",
        failure_reason: str = "invalid_provider_response",
        operation_usage: LLMTokenUsage | None = None,
    ) -> None:
        super().__init__(LLMErrorCategory.INVALID_RESPONSE, message)
        self.failure_phase = failure_phase
        self.failure_reason = failure_reason
        self.operation_usage = operation_usage
        self.operation_error_category = "invalid_response"


class LLMTruncatedResponseError(LLMInvalidResponseError):
    def __init__(self, usage: LLMTokenUsage | None = None) -> None:
        super().__init__(
            "The LLM provider truncated its completion at the output token limit.",
            failure_phase="completion_finish_reason",
            failure_reason="length",
            operation_usage=usage,
        )
        self.operation_usage = usage
        self.operation_error_category = "truncated_completion"


class LLMClient(Protocol):
    async def complete(self, messages: Sequence[LLMRequestMessage]) -> LLMCompletionResult:
        """Return one chat completion for the supplied conversation."""


def normalize_chat_completions_url(base_url: str) -> str:
    """Append the chat endpoint once, accepting either a server or endpoint URL."""
    value = base_url.strip()
    if not value:
        raise LLMConfigurationError("LLM_BASE_URL must be configured for provider mode.")
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise LLMConfigurationError("LLM_BASE_URL is not a valid URL.") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise LLMConfigurationError("LLM_BASE_URL must be an absolute HTTP or HTTPS URL.")

    path = parsed.path.rstrip("/")
    if not path.lower().endswith("/chat/completions"):
        path = f"{path}/chat/completions" if path else "/chat/completions"
    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, ""))


class OpenAICompatibleClient:
    """Small HTTPX client for providers implementing the chat-completions shape."""

    GROQ_GPT_OSS_120B = "openai/gpt-oss-120b"
    GROQ_GPT_OSS_20B = "openai/gpt-oss-20b"
    GROQ_COMPLETION_TOKEN_BUDGET = 8192
    GROQ_TPM_LIMIT = 8000
    GROQ_PROMPT_ESTIMATE_SAFETY_TOKENS = 256
    GROQ_PROMPT_BYTES_PER_TOKEN_ESTIMATE = 3.5

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout_seconds: float = 60.0,
        max_rate_limit_wait_seconds: float = 60.0,
        http_client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not model.strip():
            raise LLMConfigurationError("LLM_MODEL must be configured for provider mode.")
        if timeout_seconds <= 0:
            raise LLMConfigurationError("LLM_TIMEOUT_SECONDS must be greater than zero.")
        if http_client is not None and transport is not None:
            raise LLMConfigurationError("Provide either an HTTPX client or transport, not both.")

        self.url = normalize_chat_completions_url(base_url)
        self.model = model.strip()
        self._api_key = api_key.strip()
        self.max_rate_limit_wait_seconds = max_rate_limit_wait_seconds
        self._tpm_remaining_tokens: int | None = None
        self._tpm_reset_at: float | None = None
        self._tpm_state_lock = asyncio.Lock()
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout_seconds, transport=transport)

    async def complete(
        self,
        messages: Sequence[LLMRequestMessage],
        *,
        max_completion_tokens: int | None = None,
    ) -> LLMCompletionResult:
        if not messages:
            error = LLMInvalidResponseError(
                "At least one LLM request message is required.",
                failure_phase="request_validation",
                failure_reason="empty_messages",
            )
            _log_invalid_response(error, None, None, raw_usage=None)
            raise error

        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        body = {
            "model": self.model,
            "messages": [message.model_dump(mode="json") for message in messages],
        }
        request_prompt_characters = sum(len(message.content) for message in messages)
        request_content_bytes = sum(len(message.content.encode("utf-8")) for message in messages)
        if self.model == self.GROQ_GPT_OSS_20B:
            estimated_prompt_tokens = self._estimate_groq_prompt_tokens(request_content_bytes)
            prompt_estimate_method = "utf8_bytes_div_3_5_conservative"
        else:
            estimated_prompt_tokens = (request_prompt_characters + 3) // 4
            prompt_estimate_method = "characters_div_4_approximation"
        if max_completion_tokens is not None:
            if (
                isinstance(max_completion_tokens, bool)
                or not isinstance(max_completion_tokens, int)
                or max_completion_tokens <= 0
            ):
                raise LLMConfigurationError("The requested completion-token budget must be a positive integer.")
            effective_completion_budget = max_completion_tokens
            if self.model == self.GROQ_GPT_OSS_20B:
                available_budget = (
                    self.GROQ_TPM_LIMIT
                    - estimated_prompt_tokens
                    - self.GROQ_PROMPT_ESTIMATE_SAFETY_TOKENS
                )
                if available_budget < 1:
                    raise LLMInvalidResponseError(
                        "The prompt is too large for the provider token budget.",
                        failure_phase="request_budget_validation",
                        failure_reason="prompt_exceeds_tpm_budget",
                    )
                effective_completion_budget = min(effective_completion_budget, available_budget)
                effective_completion_budget = await self._respect_tracked_tpm_window(
                    estimated_prompt_tokens,
                    effective_completion_budget,
                )
            body["max_completion_tokens"] = effective_completion_budget
        if self.model == self.GROQ_GPT_OSS_120B:
            body.setdefault("max_completion_tokens", self.GROQ_COMPLETION_TOKEN_BUDGET)
            body["reasoning_effort"] = "low"
        request_body = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
        logger.info(
            "llm_provider_request_metadata",
            extra={
                "request_body_bytes": len(request_body),
                "request_content_bytes": request_content_bytes,
                "request_prompt_characters": request_prompt_characters,
                "estimated_prompt_tokens": estimated_prompt_tokens,
                "prompt_token_estimate_method": prompt_estimate_method,
                "request_message_count": len(messages),
                "requested_max_completion_tokens": max_completion_tokens,
                "max_completion_tokens": body.get("max_completion_tokens"),
                "tpm_window_remaining_tokens": self._tpm_remaining_tokens,
                "tpm_window_reset_seconds": self._current_tpm_reset_seconds(),
            },
        )
        try:
            response = await self._http.post(self.url, content=request_body, headers=headers)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError() from exc
        except httpx.RequestError as exc:
            raise LLMConnectionError() from exc

        self._record_tpm_window(response.headers)
        if response.status_code >= 400:
            raise _provider_error(response)

        try:
            payload = response.json()
        except (ValueError, UnicodeDecodeError) as exc:
            error = LLMInvalidResponseError(
                "The LLM provider response was not valid JSON.",
                failure_phase="provider_response_json_parse",
                failure_reason="invalid_json_body",
            )
            _log_invalid_response(error, None, None, raw_usage=None, cause=exc)
            raise error from exc

        raw_usage = payload.get("usage") if isinstance(payload, dict) else None
        try:
            usage = _parse_token_usage(raw_usage)
        except LLMInvalidResponseError as exc:
            _log_invalid_response(exc, payload, None, raw_usage=raw_usage, cause=exc.__cause__)
            raise

        response_metadata = _response_metadata(payload)
        response_metadata["typed_token_usage_available"] = usage is not None
        response_metadata["rate_limit_headers"] = _safe_rate_limit_headers(response.headers)
        response_metadata["tpm_window_remaining_tokens"] = self._tpm_remaining_tokens
        response_metadata["tpm_window_reset_seconds"] = self._current_tpm_reset_seconds()
        logger.info("llm_provider_response_metadata", extra=response_metadata)

        try:
            content, returned_model, finish_reason = self._parse_completion(payload)
        except LLMInvalidResponseError as exc:
            exc.operation_usage = usage
            _log_invalid_response(exc, payload, usage, raw_usage=raw_usage, cause=exc.__cause__)
            raise

        try:
            return LLMCompletionResult(
                content=content,
                model=returned_model or self.model,
                provider="openai-compatible",
                usage=usage,
                finish_reason=finish_reason,
                is_mock=False,
            )
        except ValidationError as exc:
            error = LLMInvalidResponseError(
                "The LLM provider response could not be represented as a completion result.",
                failure_phase="completion_result_validation",
                failure_reason="invalid_completion_result",
                operation_usage=usage,
            )
            _log_invalid_response(error, payload, usage, raw_usage=raw_usage, cause=exc)
            raise error from exc

    @classmethod
    def _estimate_groq_prompt_tokens(cls, prompt_bytes: int) -> int:
        return math.ceil(prompt_bytes / cls.GROQ_PROMPT_BYTES_PER_TOKEN_ESTIMATE)

    def _record_tpm_window(self, headers: httpx.Headers) -> None:
        if self.model != self.GROQ_GPT_OSS_20B:
            return
        safe_headers = _safe_rate_limit_headers(headers)
        remaining_value = safe_headers.get("x-ratelimit-remaining-tokens")
        reset_value = safe_headers.get("x-ratelimit-reset-tokens")
        try:
            remaining = int(remaining_value) if remaining_value is not None else None
        except ValueError:
            remaining = None
        reset_seconds = _parse_provider_duration(reset_value)
        if remaining is None or remaining < 0 or reset_seconds is None:
            return
        self._tpm_remaining_tokens = remaining
        self._tpm_reset_at = time.monotonic() + reset_seconds

    def _current_tpm_reset_seconds(self) -> float | None:
        if self._tpm_reset_at is None:
            return None
        return max(0.0, self._tpm_reset_at - time.monotonic())

    async def _respect_tracked_tpm_window(
        self,
        estimated_prompt_tokens: int,
        completion_budget: int,
    ) -> int:
        if self._tpm_remaining_tokens is None or self._tpm_reset_at is None:
            return completion_budget

        async with self._tpm_state_lock:
            remaining = self._tpm_remaining_tokens
            reset_at = self._tpm_reset_at
            delay = max(0.0, reset_at - time.monotonic())
            if delay <= 0:
                self._tpm_remaining_tokens = None
                self._tpm_reset_at = None
                return completion_budget

            available_completion = (
                remaining
                - estimated_prompt_tokens
                - self.GROQ_PROMPT_ESTIMATE_SAFETY_TOKENS
            )
            if available_completion >= completion_budget:
                return completion_budget

            if delay <= self.max_rate_limit_wait_seconds:
                logger.info(
                    "llm_tpm_window_wait",
                    extra={
                        "tpm_window_remaining_tokens": remaining,
                        "tpm_window_reset_seconds": delay,
                        "estimated_prompt_tokens": estimated_prompt_tokens,
                        "requested_max_completion_tokens": completion_budget,
                        "retry_stop_reason": "wait_for_tpm_window_reset",
                    },
                )
                await asyncio.sleep(delay + 0.01)
                if self._tpm_reset_at == reset_at:
                    self._tpm_remaining_tokens = None
                    self._tpm_reset_at = None
                return completion_budget

            if available_completion > 0:
                logger.warning(
                    "llm_tpm_budget_clamped_to_current_window",
                    extra={
                        "tpm_window_remaining_tokens": remaining,
                        "tpm_window_reset_seconds": delay,
                        "estimated_prompt_tokens": estimated_prompt_tokens,
                        "requested_max_completion_tokens": completion_budget,
                        "max_completion_tokens": available_completion,
                        "retry_stop_reason": "window_reset_exceeds_wait_cap",
                    },
                )
                return min(completion_budget, available_completion)

            raise LLMInvalidResponseError(
                "The current provider token window cannot fit this prompt; retry after the token window resets.",
                failure_phase="request_budget_validation",
                failure_reason="tpm_window_headroom_insufficient",
            )

    @staticmethod
    def _parse_completion(payload: object) -> tuple[str, str | None, str | None]:
        if not isinstance(payload, dict):
            raise LLMInvalidResponseError(
                failure_phase="completion_payload_validation",
                failure_reason="payload_not_object",
            )
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise LLMInvalidResponseError(
                failure_phase="completion_payload_validation",
                failure_reason="choices_missing_or_invalid",
            )
        choice = choices[0]
        message = choice.get("message")
        if not isinstance(message, dict):
            raise LLMInvalidResponseError(
                failure_phase="completion_payload_validation",
                failure_reason="message_missing_or_invalid",
            )
        if not isinstance(message.get("content"), str):
            raise LLMInvalidResponseError(
                failure_phase="completion_payload_validation",
                failure_reason="content_missing_or_not_string",
            )
        finish_reason = choice.get("finish_reason")
        if finish_reason is not None and not isinstance(finish_reason, str):
            raise LLMInvalidResponseError(
                "The LLM provider returned malformed completion metadata.",
                failure_phase="completion_payload_validation",
                failure_reason="finish_reason_not_string",
            )

        returned_model = payload.get("model")
        if returned_model is not None and not isinstance(returned_model, str):
            raise LLMInvalidResponseError(
                failure_phase="completion_payload_validation",
                failure_reason="model_not_string",
            )
        if returned_model == "":
            returned_model = None
        return message["content"], returned_model, _safe_finish_reason(finish_reason)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()


def _response_metadata(payload: object) -> dict[str, object]:
    """Extract response shape only; never retain provider text or reasoning content."""
    metadata: dict[str, object] = {
        "content_exists": False,
        "content_type": "missing",
        "reasoning_exists": False,
        "reasoning_content_exists": False,
        "refusal_exists": False,
        "tool_calls_exists": False,
        "finish_reason": None,
        "token_usage_present": False,
        "provider_usage_present": False,
        "typed_token_usage_available": False,
        "content_empty": None,
        "content_char_count": None,
        "usage_extra_fields": [],
    }
    if not isinstance(payload, dict):
        return metadata

    metadata["provider_usage_present"] = payload.get("usage") is not None
    metadata["token_usage_present"] = payload.get("usage") is not None
    raw_usage = payload.get("usage")
    if isinstance(raw_usage, dict):
        metadata["usage_extra_fields"] = sorted(
            key for key in raw_usage if key in _GROQ_USAGE_METADATA_FIELDS
        )
        for token_field in _TOKEN_FIELDS:
            token_count = raw_usage.get(token_field)
            metadata[token_field] = (
                token_count if isinstance(token_count, int) and not isinstance(token_count, bool)
                and token_count >= 0 else None
            )
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return metadata

    choice = choices[0]
    finish_reason = choice.get("finish_reason")
    if isinstance(finish_reason, str):
        metadata["finish_reason"] = _safe_finish_reason(finish_reason)

    message = choice.get("message")
    if not isinstance(message, dict):
        return metadata

    metadata["content_exists"] = "content" in message
    content = message.get("content")
    metadata["content_type"] = type(content).__name__ if "content" in message else "missing"
    if isinstance(content, str):
        metadata["content_empty"] = not content.strip()
        metadata["content_char_count"] = len(content)
    for field in ("reasoning", "reasoning_content", "refusal", "tool_calls"):
        metadata[f"{field}_exists"] = field in message
    return metadata


def _parse_token_usage(raw_usage: object) -> LLMTokenUsage | None:
    """Validate canonical counters while ignoring provider-specific usage metadata."""
    if raw_usage is None:
        return None
    if not isinstance(raw_usage, dict):
        raise LLMInvalidResponseError(
            "The LLM provider returned malformed token usage.",
            failure_phase="token_usage_validation",
            failure_reason="usage_not_object",
        )

    canonical_usage = {field: raw_usage[field] for field in _TOKEN_FIELDS if field in raw_usage}
    try:
        return LLMTokenUsage.model_validate(canonical_usage)
    except ValidationError as exc:
        error = LLMInvalidResponseError(
            "The LLM provider returned malformed token usage.",
            failure_phase="token_usage_validation",
            failure_reason="invalid_token_counters",
        )
        raise error from exc


def _log_invalid_response(
    error: LLMInvalidResponseError,
    payload: object | None,
    usage: LLMTokenUsage | None,
    *,
    raw_usage: object,
    cause: Exception | None = None,
) -> None:
    metadata = _response_metadata(payload) if payload is not None else {}
    validation_errors = cause.errors(include_url=False) if isinstance(cause, ValidationError) else []
    safe_errors = [
        {
            "location": [
                part if isinstance(part, int) else (
                    part if isinstance(part, str) and part in _TOKEN_FIELDS else "<unknown-field>"
                )
                for part in item.get("loc", ())
            ],
            "type": item.get("type", "unknown"),
        }
        for item in validation_errors
    ]
    metadata.update({
        "exception_class": type(error).__name__,
        "cause_exception_class": type(cause).__name__ if cause is not None else None,
        "error_category": error.category.value,
        "failure_phase": error.failure_phase,
        "failure_reason": error.failure_reason,
        "pydantic_errors": safe_errors,
        "provider_usage_present": raw_usage is not None,
        "typed_token_usage_available": usage is not None,
        "token_usage_present": usage is not None,
        "prompt_tokens": usage.prompt_tokens if usage else metadata.get("prompt_tokens"),
        "completion_tokens": usage.completion_tokens if usage else metadata.get("completion_tokens"),
        "total_tokens": usage.total_tokens if usage else metadata.get("total_tokens"),
    })
    error.operation_usage = usage
    logger.error("llm_client_invalid_response", extra=metadata)


def _safe_finish_reason(value: str | None) -> str | None:
    """Keep known protocol values while preventing arbitrary provider text in logs."""
    if value is None:
        return None
    return value if value in _KNOWN_FINISH_REASONS else "other"


def _provider_error(response: httpx.Response) -> LLMProviderError:
    """Extract only bounded structured provider diagnostics and approved headers."""
    try:
        payload = response.json()
    except (ValueError, UnicodeDecodeError):
        payload = None
    provider_error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(provider_error, dict):
        provider_error = {}

    code = _safe_provider_label(provider_error.get("code"))
    error_type = _safe_provider_label(provider_error.get("type"))
    message = _sanitize_provider_error_message(provider_error.get("message"))
    headers = _safe_rate_limit_headers(response.headers)
    rate_limit_kind = (
        _classify_rate_limit(code, error_type, message, headers)
        if response.status_code == 429 else None
    )
    retry_after = _retry_after_seconds(headers.get("retry-after"))
    rate_limit_reset = None
    if rate_limit_kind in {"rpm", "tpm"}:
        reset_key = "x-ratelimit-reset-requests" if rate_limit_kind == "rpm" else "x-ratelimit-reset-tokens"
        rate_limit_reset = _parse_provider_duration(headers.get(reset_key))
    selected_retry_delay = retry_after
    if rate_limit_kind == "tpm":
        timing_values = [value for value in (retry_after, rate_limit_reset) if value is not None]
        selected_retry_delay = max(timing_values) if timing_values else None
    elif selected_retry_delay is None:
        selected_retry_delay = rate_limit_reset

    error = LLMProviderError(
        response.status_code,
        retry_after,
        provider_error_code=code,
        provider_error_type=error_type,
        provider_error_message=message,
        rate_limit_kind=rate_limit_kind,
        rate_limit_headers=headers,
        rate_limit_reset_seconds=rate_limit_reset,
        selected_retry_delay_seconds=selected_retry_delay,
        retryable=(response.status_code == 429 and rate_limit_kind != "quota")
        or response.status_code >= 500,
    )
    log_event = "llm_provider_http_error"
    if message:
        log_event = f"{log_event}: {message}"
    logger.warning(
        log_event,
        extra={
            "http_status": response.status_code,
            "error_category": "provider_error",
            "provider_error_code": code,
            "provider_error_type": error_type,
            "provider_error_message": message,
            "rate_limit_kind": rate_limit_kind,
            "rate_limit_headers": headers,
            "retry_after_seconds": retry_after,
            "rate_limit_reset_seconds": rate_limit_reset,
            "selected_retry_delay_seconds": selected_retry_delay,
            "retryable": error.retryable,
        },
    )
    return error


def _safe_provider_label(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:100] if re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", value) else None


def _sanitize_provider_error_message(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    message = " ".join(value.split())
    message = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/-]+=*", "Bearer [REDACTED]", message)
    message = re.sub(r"(?i)gsk_[A-Za-z0-9_-]+", "[REDACTED]", message)
    message = re.sub(r"(?i)sk-[A-Za-z0-9_-]+", "[REDACTED]", message)
    message = re.sub(r"(?i)(api[_ -]?key\s*[:=]\s*)\S+", r"\1[REDACTED]", message)
    return message[:500]


def _safe_rate_limit_headers(headers: httpx.Headers) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in _RATE_LIMIT_HEADER_NAMES:
        value = headers.get(name)
        if value is None:
            continue
        # Header values are protocol metadata; discard unexpected characters and bound size.
        sanitized = re.sub(r"[^A-Za-z0-9.,:+\- ]", "", value).strip()[:64]
        if sanitized:
            result[name] = sanitized
    return result


def _classify_rate_limit(
    provider_code: str | None,
    provider_type: str | None,
    provider_message: str | None,
    headers: dict[str, str],
) -> str:
    code = (provider_code or "").lower()
    error_type = (provider_type or "").lower()
    message = (provider_message or "").lower()

    # Structured permanent quota codes take precedence over broad message matching.
    quota_codes = ("insufficient_quota", "quota", "billing", "payment", "spend_limit")
    if any(term in code or term in error_type for term in quota_codes):
        return "quota"

    # Provider code/type identify transient TPM/RPM errors even if prose mentions a quota.
    is_rate_limit_error = code in {"rate_limit_exceeded", "rate_limit_error", "too_many_requests"}
    if is_rate_limit_error or error_type in {"token", "tokens", "request", "requests"}:
        if error_type in {"token", "tokens"} or headers.get("x-ratelimit-remaining-tokens") == "0":
            return "tpm"
        if error_type in {"request", "requests"} or headers.get("x-ratelimit-remaining-requests") == "0":
            return "rpm"
        return "rate_limit"

    if any(term in message for term in ("insufficient quota", "quota", "billing", "payment", "spend limit")):
        return "quota"
    if "token" in message or headers.get("x-ratelimit-remaining-tokens") == "0":
        return "tpm"
    if "request" in message or headers.get("x-ratelimit-remaining-requests") == "0":
        return "rpm"
    return "rate_limit"


def _parse_provider_duration(value: str | None) -> float | None:
    """Parse Groq reset durations such as 1.5s, 500ms, or 1m2.5s."""
    if not value:
        return None
    match = re.fullmatch(
        r"(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m)?(?:(\d+(?:\.\d+)?)s)?(?:(\d+(?:\.\d+)?)ms)?",
        value,
    )
    if match is None or not any(match.groups()):
        return None
    hours, minutes, seconds, milliseconds = (float(part or 0) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


class MockLLMClient:
    """Deterministic transport stub that never poses as interpreted model output."""

    async def complete(self, messages: Sequence[LLMRequestMessage]) -> LLMCompletionResult:
        if not messages:
            error = LLMInvalidResponseError(
                "At least one LLM request message is required.",
                failure_phase="request_validation",
                failure_reason="empty_messages",
            )
            _log_invalid_response(error, None, None, raw_usage=None)
            raise error
        return LLMCompletionResult(
            content="[MOCK ONLY] No provider was called; this is not interpreted document content.",
            model="mock",
            provider="mock",
            usage=None,
            is_mock=True,
        )

    async def aclose(self) -> None:
        return None
