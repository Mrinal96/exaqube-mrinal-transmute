"""In-process tests for provider requests and explicit mock selection."""

import asyncio
import json
import logging

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.core.logging import JsonFormatter
from app.models.llm import LLMCompletionResult, LLMErrorCategory, LLMRequestMessage
from app.services.llm import LLMNotConfiguredError, LLMService
from app.services.llm_client import (
    LLMConnectionError,
    LLMConfigurationError,
    LLMInvalidResponseError,
    LLMProviderError,
    LLMTruncatedResponseError,
    LLMTimeoutError,
    OpenAICompatibleClient,
    normalize_chat_completions_url,
)


MESSAGES = [
    LLMRequestMessage(role="system", content="Follow the requested format."),
    LLMRequestMessage(role="user", content="Summarize this source."),
]


def run(coroutine):
    return asyncio.run(coroutine)


def make_settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "llm_base_url": "https://llm.example.test/v1",
        "llm_api_key": "test-secret",
        "llm_model": "test-model",
        "mock_llm": False,
    }
    values.update(overrides)
    return Settings(**values)


def test_retry_delay_configuration_allows_sixty_seconds_but_not_more():
    assert make_settings(llm_max_retry_delay_seconds=60).llm_max_retry_delay_seconds == 60
    with pytest.raises(ValidationError):
        make_settings(llm_max_retry_delay_seconds=60.1)


def test_retry_delay_configuration_allows_sixty_seconds_but_not_more():
    assert make_settings(llm_max_retry_delay_seconds=60).llm_max_retry_delay_seconds == 60
    with pytest.raises(ValidationError):
        make_settings(llm_max_retry_delay_seconds=60.1)


def clear_llm_environment(monkeypatch) -> None:
    for name in (
        "MOCK_LLM",
        "LLM_BASE_URL",
        "LLM_MODEL",
        "LLM_API_KEY",
        "LLM_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_openai_compatible_request_shape_model_messages_and_bearer_auth(caplog):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = request.headers
        captured["body_bytes"] = len(request.content)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "served-model",
                "choices": [{"message": {"role": "assistant", "content": "A concise result."}}],
            },
        )

    client = OpenAICompatibleClient(
        base_url="https://llm.example.test/v1",
        api_key="secret-value",
        model="requested-model",
        transport=httpx.MockTransport(handler),
    )
    with caplog.at_level(logging.INFO, logger="app.services.llm_client"):
        result = run(_complete_and_close(client))

    assert captured["url"] == "https://llm.example.test/v1/chat/completions"
    assert captured["headers"]["authorization"] == "Bearer secret-value"
    assert captured["body"] == {
        "model": "requested-model",
        "messages": [message.model_dump(mode="json") for message in MESSAGES],
    }
    assert result.content == "A concise result."
    assert result.model == "served-model"
    assert result.provider == "openai-compatible"
    request_log = next(record for record in caplog.records if record.message == "llm_provider_request_metadata")
    assert request_log.request_body_bytes == captured["body_bytes"]
    assert request_log.request_content_bytes == sum(len(message.content.encode("utf-8")) for message in MESSAGES)
    assert request_log.request_prompt_characters == sum(len(message.content) for message in MESSAGES)
    assert request_log.estimated_prompt_tokens == (request_log.request_prompt_characters + 3) // 4
    assert request_log.request_message_count == len(MESSAGES)
    assert result.is_mock is False


def test_groq_gpt_oss_request_uses_supported_completion_budget_and_low_reasoning_effort():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]},
        )

    client = OpenAICompatibleClient(
        base_url="https://api.groq.com/openai/v1",
        model="openai/gpt-oss-120b",
        transport=httpx.MockTransport(handler),
    )
    run(_complete_and_close(client))

    assert captured["body"]["max_completion_tokens"] == 8192
    assert captured["body"]["reasoning_effort"] == "low"
    assert "max_tokens" not in captured["body"]


def test_groq_gpt_oss_20b_workflow_budget_is_sent_and_kept_within_tpm_headroom():
    captured = {}
    messages = [
        LLMRequestMessage(role="system", content="Interpret the source faithfully."),
        LLMRequestMessage(role="user", content="A compact financial source."),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]},
        )

    client = OpenAICompatibleClient(
        base_url="https://api.groq.com/openai/v1",
        model="openai/gpt-oss-20b",
        transport=httpx.MockTransport(handler),
    )
    service = LLMService(
        make_settings(model="openai/gpt-oss-20b"),
        client=client,
    )
    run(_service_complete_with_budget_and_close(service, messages, 4096))

    estimated_prompt_tokens = (sum(len(message.content) for message in messages) + 3) // 4
    assert captured["body"]["max_completion_tokens"] == 4096
    assert "max_tokens" not in captured["body"]
    assert (
        estimated_prompt_tokens
        + captured["body"]["max_completion_tokens"]
        + client.GROQ_PROMPT_ESTIMATE_SAFETY_TOKENS
        <= client.GROQ_TPM_LIMIT
    )


def test_groq_gpt_oss_20b_workflow_budget_clamps_for_large_prompts():
    captured = {}
    long_messages = [LLMRequestMessage(role="user", content="x" * 20_000)]

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]},
        )

    client = OpenAICompatibleClient(
        base_url="https://api.groq.com/openai/v1",
        model="openai/gpt-oss-20b",
        transport=httpx.MockTransport(handler),
    )
    service = LLMService(make_settings(model="openai/gpt-oss-20b"), client=client)
    run(_service_complete_with_budget_and_close(service, long_messages, 4096))

    estimated_prompt_tokens = (len(long_messages[0].content) + 3) // 4
    assert captured["body"]["max_completion_tokens"] == (
        client.GROQ_TPM_LIMIT
        - estimated_prompt_tokens
        - client.GROQ_PROMPT_ESTIMATE_SAFETY_TOKENS
    )


def test_length_finish_reason_is_classified_as_truncated_before_json_validation(caplog):
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{
                    "message": {"content": '{"summary":"incomplete'},
                    "finish_reason": "length",
                }],
                "usage": {"prompt_tokens": 3492, "completion_tokens": 3072, "total_tokens": 6564},
            },
        )

    provider = OpenAICompatibleClient(
        base_url="https://api.groq.com/openai/v1",
        model="openai/gpt-oss-120b",
        transport=httpx.MockTransport(handler),
    )
    service = LLMService(make_settings(), client=provider)
    with pytest.raises(LLMTruncatedResponseError, match="truncated"):
        run(_service_complete_and_close(service))

    record = next(record for record in caplog.records if record.msg == "llm_completion_truncated")
    assert record.exception_class == "LLMTruncatedResponseError"
    assert record.error_category == "truncated_completion"
    assert record.finish_reason == "length"
    assert record.prompt_tokens == 3492
    assert record.completion_tokens == 3072
    assert record.total_tokens == 6564
    assert '{"summary"' not in caplog.text


def test_api_key_is_optional():
    captured_headers = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.update(request.headers)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = OpenAICompatibleClient(
        base_url="https://llm.example.test/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    run(_complete_and_close(client))
    assert "authorization" not in captured_headers


def test_service_allows_provider_mode_without_api_key():
    captured_headers = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.update(request.headers)
        return httpx.Response(200, json={"choices": [{"message": {"content": "unauthenticated provider"}}]})

    service = LLMService(
        make_settings(llm_api_key=""),
        transport=httpx.MockTransport(handler),
    )
    result = run(_service_complete_and_close(service))
    assert result.content == "unauthenticated provider"
    assert result.is_mock is False
    assert "authorization" not in captured_headers


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("https://llm.example.test", "https://llm.example.test/chat/completions"),
        ("https://llm.example.test/v1/", "https://llm.example.test/v1/chat/completions"),
        (
            "https://llm.example.test/v1/chat/completions/",
            "https://llm.example.test/v1/chat/completions",
        ),
    ],
)
def test_chat_completions_url_normalization(base_url, expected):
    assert normalize_chat_completions_url(base_url) == expected


def test_provider_token_usage_is_parsed():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "usage included"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19},
            },
        )

    client = OpenAICompatibleClient(
        base_url="https://llm.example.test/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    result = run(_complete_and_close(client))
    assert result.usage is not None
    assert result.usage.prompt_tokens == 12
    assert result.usage.completion_tokens == 7
    assert result.usage.total_tokens == 19
    assert result.finish_reason == "stop"


def test_groq_shaped_usage_metadata_does_not_invalidate_completion(caplog):
    final_content = '{"summary":"Final answer only."}'
    response_body = {
        "model": "openai/gpt-oss-120b",
        "choices": [{
            "message": {
                "content": final_content,
                "reasoning": "private reasoning must not replace final content",
            },
            "finish_reason": "stop",
        }],
        "usage": {
            "queue_time": 0.01,
            "prompt_tokens": 3482,
            "prompt_time": 0.02,
            "completion_tokens": 2600,
            "completion_time": 1.2,
            "total_tokens": 6082,
            "total_time": 1.22,
        },
    }
    client = OpenAICompatibleClient(
        base_url="https://api.groq.com/openai/v1",
        model="openai/gpt-oss-120b",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response_body)),
    )
    caplog.set_level(logging.INFO)
    result = run(_complete_and_close(client))

    assert result.content == final_content
    assert result.usage is not None
    assert result.usage.prompt_tokens == 3482
    assert result.usage.completion_tokens == 2600
    assert result.usage.total_tokens == 6082
    assert result.finish_reason == "stop"
    metadata = next(record for record in caplog.records if record.msg == "llm_provider_response_metadata")
    assert metadata.content_empty is False
    assert metadata.content_char_count == len(final_content)
    assert metadata.reasoning_exists is True
    assert metadata.provider_usage_present is True
    assert metadata.usage_extra_fields == ["completion_time", "prompt_time", "queue_time", "total_time"]
    assert "private reasoning must not replace final content" not in caplog.text
    assert final_content not in caplog.text
    safe_log = json.dumps(JsonFormatter().format(metadata))
    assert final_content not in safe_log
    assert "private reasoning must not replace final content" not in safe_log


def test_completion_payload_failure_retains_already_parsed_provider_usage(caplog):
    response_body = {
        "choices": [{}],
        "usage": {
            "prompt_tokens": 3482,
            "completion_tokens": 2600,
            "total_tokens": 6082,
            "prompt_time": 0.02,
            "completion_time": 1.2,
        },
    }
    client = OpenAICompatibleClient(
        base_url="https://api.groq.com/openai/v1",
        model="openai/gpt-oss-120b",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response_body)),
    )
    with pytest.raises(LLMInvalidResponseError) as error_info:
        run(_complete_and_close(client))

    assert error_info.value.failure_phase == "completion_payload_validation"
    assert error_info.value.failure_reason == "message_missing_or_invalid"
    assert error_info.value.operation_usage is not None
    assert error_info.value.operation_usage.total_tokens == 6082
    record = next(record for record in caplog.records if record.msg == "llm_client_invalid_response")
    assert record.provider_usage_present is True
    assert record.typed_token_usage_available is True
    assert record.prompt_tokens == 3482
    assert record.completion_tokens == 2600
    assert record.total_tokens == 6082
    assert record.failure_phase == "completion_payload_validation"


def test_invalid_groq_usage_counter_is_diagnosed_without_typed_usage(caplog):
    response_body = {
        "choices": [{"message": {"content": "safe"}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": -1,
            "total_tokens": 9,
            "prompt_time": 0.02,
        },
    }
    client = OpenAICompatibleClient(
        base_url="https://api.groq.com/openai/v1",
        model="openai/gpt-oss-120b",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response_body)),
    )
    with pytest.raises(LLMInvalidResponseError) as error_info:
        run(_complete_and_close(client))

    assert error_info.value.failure_phase == "token_usage_validation"
    assert error_info.value.operation_usage is None
    assert isinstance(error_info.value.__cause__, Exception)
    record = next(record for record in caplog.records if record.msg == "llm_client_invalid_response")
    assert record.provider_usage_present is True
    assert record.typed_token_usage_available is False
    assert record.failure_phase == "token_usage_validation"
    assert record.pydantic_errors
    assert record.pydantic_errors[0] == {
        "location": ["completion_tokens"],
        "type": "greater_than_equal",
    }
    assert "safe" not in caplog.text


def test_provider_response_metadata_is_logged_without_response_content(caplog):
    secret_response_text = "private response text"
    caplog.set_level(logging.INFO, logger="app.services.llm_client")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{
                    "finish_reason": "stop",
                    "message": {
                        "content": secret_response_text,
                        "reasoning": "private reasoning",
                        "reasoning_content": "private reasoning content",
                        "refusal": None,
                        "tool_calls": [],
                    },
                }],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    client = OpenAICompatibleClient(
        base_url="https://llm.example.test/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    run(_complete_and_close(client))

    record = next(record for record in caplog.records if record.msg == "llm_provider_response_metadata")
    assert record.content_exists is True
    assert record.content_type == "str"
    assert record.reasoning_exists is True
    assert record.reasoning_content_exists is True
    assert record.refusal_exists is True
    assert record.tool_calls_exists is True
    assert record.finish_reason == "stop"
    assert record.token_usage_present is True
    assert record.prompt_tokens == 1
    assert record.completion_tokens == 1
    assert record.total_tokens == 2
    assert secret_response_text not in caplog.text
    assert "private reasoning" not in caplog.text
    serialized = json.loads(JsonFormatter().format(record))
    assert serialized["content_type"] == "str"
    assert serialized["reasoning_content_exists"] is True
    assert serialized["finish_reason"] == "stop"
    assert serialized["prompt_tokens"] == 1
    assert serialized["total_tokens"] == 2
    assert secret_response_text not in json.dumps(serialized)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{}]}),
        httpx.Response(200, json={"choices": [{"message": {"content": None}}]}),
        httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": -1}}),
        httpx.Response(200, content=b"not-json"),
    ],
)
def test_missing_or_malformed_provider_response_is_typed(response):
    client = OpenAICompatibleClient(
        base_url="https://llm.example.test/v1",
        model="test-model",
        transport=httpx.MockTransport(lambda _: response),
    )
    with pytest.raises(LLMInvalidResponseError):
        run(_complete_and_close(client))


@pytest.mark.parametrize("status_code", [400, 503])
def test_http_errors_are_typed_and_retryability_is_classified(status_code):
    client = OpenAICompatibleClient(
        base_url="https://llm.example.test/v1",
        model="test-model",
        transport=httpx.MockTransport(lambda _: httpx.Response(status_code, text="sensitive provider detail")),
    )
    with pytest.raises(LLMProviderError) as error_info:
        run(_complete_and_close(client))
    assert error_info.value.status_code == status_code
    assert error_info.value.retryable is (status_code >= 500)
    assert "sensitive provider detail" not in str(error_info.value)


def test_rate_limit_provider_error_is_retryable():
    client = OpenAICompatibleClient(
        base_url="https://llm.example.test/v1",
        model="test-model",
        transport=httpx.MockTransport(lambda _: httpx.Response(429)),
    )
    with pytest.raises(LLMProviderError) as error_info:
        run(_complete_and_close(client))
    assert error_info.value.retryable is True


def test_rate_limit_retry_after_is_parsed_and_bounded():
    client = OpenAICompatibleClient(
        base_url="https://llm.example.test/v1",
        model="test-model",
        transport=httpx.MockTransport(lambda _: httpx.Response(429, headers={"Retry-After": "7"})),
    )
    with pytest.raises(LLMProviderError) as error_info:
        run(_complete_and_close(client))
    assert error_info.value.retry_after_seconds == 7


@pytest.mark.parametrize(
    ("error_type", "message", "headers", "expected_kind"),
    [
        (
            "requests",
            "Rate limit reached for requests per minute; credential gsk_sensitive_value",
            {
                "Retry-After": "0.25",
                "x-ratelimit-limit-requests": "30",
                "x-ratelimit-remaining-requests": "0",
                "x-ratelimit-reset-requests": "1.2s",
            },
            "rpm",
        ),
        (
            "tokens",
            "Rate limit reached for tokens per minute",
            {"x-ratelimit-remaining-tokens": "0", "x-ratelimit-reset-tokens": "1m2.5s"},
            "tpm",
        ),
    ],
)
def test_rate_limit_error_metadata_is_safely_logged(error_type, message, headers, expected_kind, caplog):
    caplog.set_level(logging.WARNING, logger="app.services.llm_client")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers=headers, json={
            "error": {"type": error_type, "code": "rate_limit_exceeded", "message": message},
        })

    client = OpenAICompatibleClient(
        base_url="https://llm.example.test/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(LLMProviderError) as error_info:
        run(_complete_and_close(client))

    error = error_info.value
    assert error.status_code == 429
    assert error.retryable is True
    assert error.rate_limit_kind == expected_kind
    assert error.provider_error_code == "rate_limit_exceeded"
    assert error.provider_error_type == error_type
    assert error.retry_after_seconds == (0.25 if expected_kind == "rpm" else None)
    assert error.rate_limit_reset_seconds == (1.2 if expected_kind == "rpm" else 62.5)
    assert error.selected_retry_delay_seconds == (0.25 if expected_kind == "rpm" else 62.5)
    record = next(record for record in caplog.records if record.getMessage().startswith("llm_provider_http_error"))
    assert record.http_status == 429
    assert record.rate_limit_kind == expected_kind
    assert record.rate_limit_headers
    assert "credential gsk_sensitive_value" not in caplog.text
    assert "gsk_sensitive_value" not in caplog.text
    structured = json.loads(JsonFormatter().format(record))
    assert structured["provider_error_code"] == "rate_limit_exceeded"
    assert structured["provider_error_message"] == record.provider_error_message
    assert structured["rate_limit_headers"]
    assert "gsk_sensitive_value" not in json.dumps(structured)


def _groq_tpm_limit_response() -> httpx.Response:
    return httpx.Response(
        429,
        headers={
            "Retry-After": "19",
            "x-ratelimit-limit-tokens": "8000",
            "x-ratelimit-remaining-tokens": "0",
            "x-ratelimit-reset-tokens": "41.985s",
        },
        json={
            "error": {
                "message": "Rate limit reached for tokens per minute. Limit 8000 TPM, Used 5546, Requested 6008.",
                "type": "tokens",
                "code": "rate_limit_exceeded",
            },
        },
    )


def test_groq_tpm_limit_structure_is_transient_and_retry_after_is_preserved():
    client = OpenAICompatibleClient(
        base_url="https://api.groq.com/openai/v1",
        model="test-model",
        transport=httpx.MockTransport(lambda _: _groq_tpm_limit_response()),
    )

    with pytest.raises(LLMProviderError) as error_info:
        run(_complete_and_close(client))

    error = error_info.value
    assert error.status_code == 429
    assert error.provider_error_code == "rate_limit_exceeded"
    assert error.provider_error_type == "tokens"
    assert error.rate_limit_kind == "tpm"
    assert error.retryable is True
    assert error.retry_after_seconds == 19
    assert error.rate_limit_reset_seconds == 41.985
    assert error.selected_retry_delay_seconds == 41.985
    assert error.rate_limit_headers["x-ratelimit-limit-tokens"] == "8000"


def test_service_honors_groq_tpm_retry_after_when_within_configured_cap(monkeypatch, caplog):
    calls = 0
    delays = []
    caplog.set_level(logging.WARNING, logger="app.services.llm")

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return _groq_tpm_limit_response()
        return httpx.Response(200, json={"choices": [{"message": {"content": "retry succeeded"}}]})

    async def record_wait(delay):
        delays.append(delay)

    monkeypatch.setattr("app.services.llm.asyncio.sleep", record_wait)
    client = OpenAICompatibleClient(
        base_url="https://api.groq.com/openai/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    service = LLMService(
        make_settings(llm_max_attempts=2, llm_max_retry_delay_seconds=60),
        client=client,
    )

    result = run(_service_complete_and_close(service))

    assert result.content == "retry succeeded"
    assert calls == 2
    assert delays == [41.985]
    retry = next(record for record in caplog.records if record.msg == "llm_retry_scheduled")
    assert retry.rate_limit_kind == "tpm"
    assert retry.attempt == 1
    assert retry.retry_after_seconds == 19
    assert retry.rate_limit_reset_seconds == 41.985
    assert retry.delay_seconds == 41.985
    assert retry.selected_retry_delay_seconds == 41.985


def test_groq_tpm_retry_after_above_cap_stops_without_early_retry(caplog):
    calls = 0
    caplog.set_level(logging.WARNING, logger="app.services.llm")

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _groq_tpm_limit_response()

    client = OpenAICompatibleClient(
        base_url="https://api.groq.com/openai/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    service = LLMService(
        make_settings(llm_max_attempts=3, llm_max_retry_delay_seconds=40),
        client=client,
    )

    with pytest.raises(LLMProviderError) as error_info:
        run(_service_complete_and_close(service))

    assert error_info.value.rate_limit_kind == "tpm"
    assert error_info.value.retryable is True
    assert calls == 1
    stopped = next(record for record in caplog.records if record.msg == "llm_retry_stopped")
    assert stopped.attempt == 1
    assert stopped.rate_limit_kind == "tpm"
    assert stopped.retry_after_seconds == 19
    assert stopped.rate_limit_reset_seconds == 41.985
    assert stopped.delay_seconds == 41.985
    assert stopped.selected_retry_delay_seconds == 41.985
    assert stopped.retry_stop_reason == "retry_after_exceeds_max_delay"


def test_structured_quota_error_is_not_retryable_or_logged_with_full_body(caplog):
    caplog.set_level(logging.WARNING, logger="app.services.llm_client")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "1"}, json={
            "error": {
                "type": "insufficient_quota",
                "code": "insufficient_quota",
                "message": "You exceeded your billing quota.",
                "private_detail": "DO_NOT_LOG_THIS",
            },
        })

    client = OpenAICompatibleClient(
        base_url="https://llm.example.test/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(LLMProviderError) as error_info:
        run(_complete_and_close(client))

    assert error_info.value.rate_limit_kind == "quota"
    assert error_info.value.retryable is False
    assert "You exceeded your billing quota." in caplog.text
    assert "DO_NOT_LOG_THIS" not in caplog.text
    record = next(record for record in caplog.records if record.getMessage().startswith("llm_provider_http_error"))
    structured = json.loads(JsonFormatter().format(record))
    assert structured["provider_error_code"] == "insufficient_quota"
    assert structured["provider_error_message"] == "You exceeded your billing quota."
    assert structured["http_status"] == 429
    assert structured["rate_limit_kind"] == "quota"
    assert "DO_NOT_LOG_THIS" not in json.dumps(structured)


@pytest.mark.parametrize(
    ("raised", "error_type"),
    [
        (httpx.ReadTimeout("private timeout"), LLMTimeoutError),
        (httpx.ConnectError("private connection detail"), LLMConnectionError),
    ],
)
def test_timeout_and_connection_failures_are_typed(raised, error_type):
    client = OpenAICompatibleClient(
        base_url="https://llm.example.test/v1",
        model="test-model",
        transport=httpx.MockTransport(lambda _: _raise(raised)),
    )
    with pytest.raises(error_type) as error_info:
        run(_complete_and_close(client))
    assert "private" not in str(error_info.value)


def test_mock_setting_selects_explicit_mock_result(monkeypatch):
    clear_llm_environment(monkeypatch)
    monkeypatch.setenv("MOCK_LLM", "true")
    settings = Settings(_env_file=None)
    assert settings.mock_llm is True
    service = LLMService(settings)
    result = run(_service_complete_and_close(service))
    assert result.is_mock is True
    assert result.provider == "mock"
    assert result.model == "mock"
    assert result.content.startswith("[MOCK ONLY]")
    assert result.usage is None


def test_real_provider_failure_does_not_fall_back_to_mock():
    settings = make_settings(mock_llm=False)
    service = LLMService(
        settings,
        transport=httpx.MockTransport(lambda _: httpx.Response(503)),
    )
    with pytest.raises(LLMProviderError):
        run(_service_complete_and_close(service))


def test_real_provider_mode_requires_complete_configuration(monkeypatch):
    clear_llm_environment(monkeypatch)
    monkeypatch.setenv("MOCK_LLM", "false")
    settings = Settings(_env_file=None)
    assert settings.mock_llm is False
    assert settings.llm_base_url == ""
    assert settings.llm_model == ""
    assert settings.llm_api_key.get_secret_value() == ""
    with pytest.raises(LLMNotConfiguredError) as error_info:
        LLMService(settings)
    assert error_info.value.category is LLMErrorCategory.CONFIGURATION
    assert "LLM_API_KEY is optional" in str(error_info.value)


def test_invalid_provider_url_is_configuration_error():
    with pytest.raises(LLMConfigurationError):
        OpenAICompatibleClient(base_url="not-a-url", model="test-model")


def test_service_retries_only_retryable_errors_and_stops_after_success(monkeypatch):
    class SequenceClient:
        def __init__(self):
            self.calls = 0

        async def complete(self, messages):
            self.calls += 1
            if self.calls < 3:
                raise LLMConnectionError()
            return LLMCompletionResult(content="ok", model="test-model", provider="test")

    async def no_wait(_):
        return None

    monkeypatch.setattr("app.services.llm.asyncio.sleep", no_wait)
    provider = SequenceClient()
    service = LLMService(make_settings(llm_max_attempts=3), client=provider)
    result = run(_service_complete_and_close(service))
    assert result.content == "ok"
    assert provider.calls == 3


def test_service_does_not_retry_permanent_provider_errors(monkeypatch):
    class PermanentClient:
        calls = 0

        async def complete(self, messages):
            self.calls += 1
            raise LLMProviderError(400)

    async def unexpected_wait(_):
        raise AssertionError("Permanent provider errors must not be retried.")

    monkeypatch.setattr("app.services.llm.asyncio.sleep", unexpected_wait)
    provider = PermanentClient()
    service = LLMService(make_settings(llm_max_attempts=4), client=provider)
    with pytest.raises(LLMProviderError):
        run(_service_complete_and_close(service))
    assert provider.calls == 1


def test_service_honors_valid_retry_after_hint(monkeypatch):
    class RateLimitedOnce:
        calls = 0

        async def complete(self, messages):
            self.calls += 1
            if self.calls == 1:
                raise LLMProviderError(429, retry_after_seconds=2.5)
            return LLMCompletionResult(content="ok", model="test-model", provider="test")

    delays = []

    async def record_wait(delay):
        delays.append(delay)

    monkeypatch.setattr("app.services.llm.asyncio.sleep", record_wait)
    provider = RateLimitedOnce()
    service = LLMService(make_settings(llm_max_attempts=2), client=provider)
    assert run(_service_complete_and_close(service)).content == "ok"
    assert delays == [2.5]
    assert provider.calls == 2


def test_service_retries_transient_rate_limit_and_logs_attempt_and_delay(monkeypatch, caplog):
    calls = 0
    delays = []
    caplog.set_level(logging.WARNING, logger="app.services.llm")

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={
                "error": {"type": "requests", "code": "rate_limit_exceeded", "message": "Request rate limit reached."},
            })
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    async def record_wait(delay):
        delays.append(delay)

    monkeypatch.setattr("app.services.llm.asyncio.sleep", record_wait)
    client = OpenAICompatibleClient(
        base_url="https://llm.example.test/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    service = LLMService(make_settings(llm_max_attempts=3), client=client)

    result = run(_service_complete_and_close(service))

    assert result.content == "ok"
    assert calls == 2
    assert delays == [0.0]
    retry = next(record for record in caplog.records if record.msg == "llm_retry_scheduled")
    assert retry.attempt == 1
    assert retry.next_attempt == 2
    assert retry.max_attempts == 3
    assert retry.delay_seconds == 0.0
    assert retry.rate_limit_kind == "rpm"


def test_service_stops_after_configured_rate_limit_retry_exhaustion(monkeypatch, caplog):
    calls = 0
    delays = []
    caplog.set_level(logging.WARNING, logger="app.services.llm")

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "0"}, json={
            "error": {"type": "tokens", "code": "rate_limit_exceeded", "message": "Token rate limit reached."},
        })

    async def record_wait(delay):
        delays.append(delay)

    monkeypatch.setattr("app.services.llm.asyncio.sleep", record_wait)
    client = OpenAICompatibleClient(
        base_url="https://llm.example.test/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    service = LLMService(make_settings(llm_max_attempts=3), client=client)

    with pytest.raises(LLMProviderError):
        run(_service_complete_and_close(service))

    assert calls == 3
    assert delays == [0.0, 0.0]
    stopped = next(record for record in caplog.records if record.msg == "llm_retry_stopped")
    assert stopped.attempt == 3
    assert stopped.max_attempts == 3
    assert stopped.retry_stop_reason == "attempts_exhausted"


def test_service_backoff_uses_jitter_and_respects_max_delay(monkeypatch):
    class ConnectionLimitedThenSuccess:
        calls = 0

        async def complete(self, messages):
            self.calls += 1
            if self.calls < 3:
                raise LLMConnectionError()
            return LLMCompletionResult(content="ok", model="test-model", provider="test")

    delays = []

    async def record_wait(delay):
        delays.append(delay)

    monkeypatch.setattr("app.services.llm.asyncio.sleep", record_wait)
    monkeypatch.setattr("app.services.llm.random.uniform", lambda low, high: 0.25)
    provider = ConnectionLimitedThenSuccess()
    service = LLMService(
        make_settings(llm_max_attempts=3, llm_max_retry_delay_seconds=0.6),
        client=provider,
    )

    assert run(_service_complete_and_close(service)).content == "ok"
    assert provider.calls == 3
    assert delays == [0.6, 0.6]


def test_service_does_not_retry_quota_429_or_exceed_retry_after_cap(monkeypatch, caplog):
    calls = 0
    caplog.set_level(logging.WARNING, logger="app.services.llm")

    def quota_handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, json={
            "error": {"type": "insufficient_quota", "code": "insufficient_quota", "message": "Billing quota exceeded."},
        })

    async def unexpected_wait(_):
        raise AssertionError("Quota failures must not be retried.")

    monkeypatch.setattr("app.services.llm.asyncio.sleep", unexpected_wait)
    quota_client = OpenAICompatibleClient(
        base_url="https://llm.example.test/v1",
        model="test-model",
        transport=httpx.MockTransport(quota_handler),
    )
    quota_service = LLMService(make_settings(llm_max_attempts=4), client=quota_client)
    with pytest.raises(LLMProviderError):
        run(_service_complete_and_close(quota_service))
    assert calls == 1
    quota_stop = next(record for record in caplog.records if record.msg == "llm_retry_stopped")
    assert quota_stop.retry_stop_reason == "permanent_provider_error"
    assert quota_stop.rate_limit_kind == "quota"

    calls = 0

    def long_retry_handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "8"}, json={
            "error": {"type": "requests", "code": "rate_limit_exceeded", "message": "Request rate limit reached."},
        })

    capped_client = OpenAICompatibleClient(
        base_url="https://llm.example.test/v1",
        model="test-model",
        transport=httpx.MockTransport(long_retry_handler),
    )
    capped_service = LLMService(
        make_settings(llm_max_attempts=4, llm_max_retry_delay_seconds=3),
        client=capped_client,
    )
    with pytest.raises(LLMProviderError):
        run(_service_complete_and_close(capped_service))
    assert calls == 1
    cap_stop = [record for record in caplog.records if record.msg == "llm_retry_stopped"][-1]
    assert cap_stop.retry_stop_reason == "retry_after_exceeds_max_delay"


def _raise(error: Exception):
    raise error


async def _complete_and_close(client: OpenAICompatibleClient):
    try:
        return await client.complete(MESSAGES)
    finally:
        await client.aclose()


async def _service_complete_and_close(service: LLMService):
    try:
        return await service.complete(MESSAGES)
    finally:
        await service.aclose()


async def _service_complete_with_budget_and_close(service: LLMService, messages, budget: int):
    try:
        return await service.complete(messages, max_completion_tokens=budget)
    finally:
        await service.aclose()
