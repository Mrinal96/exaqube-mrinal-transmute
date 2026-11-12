"""Provider-neutral LLM service selection and completion boundary."""

from collections.abc import Sequence
import asyncio
import logging
import random

import httpx

from app.config import Settings
from app.models.llm import LLMCompletionResult, LLMRequestMessage
from app.services.llm_client import (
    LLMClient,
    LLMClientError,
    LLMConfigurationError,
    MockLLMClient,
    OpenAICompatibleClient,
    LLMTruncatedResponseError,
)


logger = logging.getLogger(__name__)


class LLMNotConfiguredError(LLMConfigurationError):
    """Backward-compatible name for missing provider settings."""


class LLMService:
    def __init__(
        self,
        settings: Settings,
        *,
        client: LLMClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        if client is not None:
            self.client = client
        elif settings.mock_llm:
            self.client = MockLLMClient()
        else:
            if not settings.llm_configured:
                raise LLMNotConfiguredError(
                    "LLM provider mode requires LLM_BASE_URL and LLM_MODEL; LLM_API_KEY is optional."
                )
            self.client = OpenAICompatibleClient(
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key.get_secret_value(),
                model=settings.llm_model,
                timeout_seconds=settings.llm_timeout_seconds,
                transport=transport,
            )

    @property
    def is_available(self) -> bool:
        return True

    async def complete(
        self,
        messages: Sequence[LLMRequestMessage],
        *,
        max_completion_tokens: int | None = None,
    ) -> LLMCompletionResult:
        for attempt in range(self.settings.llm_max_attempts):
            try:
                if max_completion_tokens is not None and isinstance(self.client, OpenAICompatibleClient):
                    result = await self.client.complete(
                        messages,
                        max_completion_tokens=max_completion_tokens,
                    )
                else:
                    result = await self.client.complete(messages)
                if result.finish_reason == "length":
                    usage = result.usage
                    logger.warning(
                        "llm_completion_truncated",
                        extra={
                            "exception_class": LLMTruncatedResponseError.__name__,
                            "error_category": "truncated_completion",
                            "finish_reason": "length",
                            "token_usage_present": usage is not None,
                            "prompt_tokens": usage.prompt_tokens if usage else None,
                            "completion_tokens": usage.completion_tokens if usage else None,
                            "total_tokens": usage.total_tokens if usage else None,
                        },
                    )
                    raise LLMTruncatedResponseError(usage)
                return result
            except LLMClientError as exc:
                attempt_number = attempt + 1
                max_attempts = self.settings.llm_max_attempts
                retry_timings = {
                    "retry_after_seconds": exc.retry_after_seconds,
                    "rate_limit_reset_seconds": getattr(exc, "rate_limit_reset_seconds", None),
                    "selected_retry_delay_seconds": getattr(exc, "selected_retry_delay_seconds", None),
                }
                if not exc.retryable:
                    logger.warning(
                        "llm_retry_stopped",
                        extra={
                            "attempt": attempt_number,
                            "max_attempts": max_attempts,
                            "retryable": False,
                            "http_status": getattr(exc, "status_code", None),
                            "provider_error_code": getattr(exc, "provider_error_code", None),
                            "rate_limit_kind": getattr(exc, "rate_limit_kind", None),
                            "retry_stop_reason": "permanent_provider_error",
                            **retry_timings,
                        },
                    )
                    raise
                if attempt_number >= max_attempts:
                    logger.warning(
                        "llm_retry_stopped",
                        extra={
                            "attempt": attempt_number,
                            "max_attempts": max_attempts,
                            "retryable": True,
                            "http_status": getattr(exc, "status_code", None),
                            "provider_error_code": getattr(exc, "provider_error_code", None),
                            "rate_limit_kind": getattr(exc, "rate_limit_kind", None),
                            "retry_stop_reason": "attempts_exhausted",
                            **retry_timings,
                        },
                    )
                    raise
                delay = getattr(exc, "selected_retry_delay_seconds", None)
                if delay is None:
                    delay = exc.retry_after_seconds
                if delay is not None and delay > self.settings.llm_max_retry_delay_seconds:
                    logger.warning(
                        "llm_retry_stopped",
                        extra={
                            "attempt": attempt_number,
                            "max_attempts": max_attempts,
                            "retryable": True,
                            "http_status": getattr(exc, "status_code", None),
                            "provider_error_code": getattr(exc, "provider_error_code", None),
                            "rate_limit_kind": getattr(exc, "rate_limit_kind", None),
                            "delay_seconds": delay,
                            "retry_stop_reason": "retry_after_exceeds_max_delay",
                            **retry_timings,
                        },
                    )
                    raise
                if delay is None:
                    delay = min(
                        min(0.5 * (2 ** attempt), self.settings.llm_max_retry_delay_seconds)
                        + random.uniform(0.0, 0.25),
                        self.settings.llm_max_retry_delay_seconds,
                    )
                logger.warning(
                    "llm_retry_scheduled",
                    extra={
                        "attempt": attempt_number,
                        "next_attempt": attempt_number + 1,
                        "max_attempts": max_attempts,
                        "delay_seconds": delay,
                        "retry_after_seconds": exc.retry_after_seconds,
                        "http_status": getattr(exc, "status_code", None),
                        "provider_error_code": getattr(exc, "provider_error_code", None),
                        "rate_limit_kind": getattr(exc, "rate_limit_kind", None),
                        "retryable": True,
                        "rate_limit_reset_seconds": getattr(exc, "rate_limit_reset_seconds", None),
                        "selected_retry_delay_seconds": delay,
                    },
                )
                await asyncio.sleep(delay)
        raise RuntimeError("LLM retry loop exited unexpectedly.")

    async def aclose(self) -> None:
        close = getattr(self.client, "aclose", None)
        if close is not None:
            await close()

    async def transform(self, *_: object, **__: object) -> None:
        raise NotImplementedError("Semantic interpretation and transformation are planned for a later milestone.")

