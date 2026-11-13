"""Integration tests for synchronous interpretation and planning APIs."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from io import BytesIO
import json
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from bs4 import BeautifulSoup
from docx import Document as WordDocument
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from pptx import Presentation

from app.config import Settings, get_settings
from app.api.operation_responses import usage_and_cost
from app.core.logging import JsonFormatter, log_context
from app.main import app
from app.models.llm import LLMCompletionResult, LLMTokenUsage
from app.services.container import get_interpretation_service, get_planning_service
from app.services.interpretation import InterpretationService
from app.services.llm import LLMService
from app.services.planning import PlanningService
from app.services.llm_client import LLMInvalidResponseError, LLMProviderError, OpenAICompatibleClient
from app.orchestration.engine import WorkflowExecutor
from app.storage.interpretations import InterpretationStore
from app.storage.transformations import TransformationStore


class StaticClient:
    def __init__(
        self,
        *,
        is_mock: bool = True,
        usage: LLMTokenUsage | None = None,
        error: Exception | None = None,
        content: str | None = None,
        finish_reason: str | None = None,
    ):
        self.is_mock = is_mock
        self.usage = usage
        self.error = error
        self.content = content or '{"summary":"Provider summary","facts":[],"metrics":[],"entities":[],"claims":[],"relationships":[],"insights":[],"warnings":[]}'
        self.finish_reason = finish_reason
        self.calls = 0

    async def complete(self, messages):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return LLMCompletionResult(
            content=self.content,
            model="api-test-model",
            provider="api-test-provider",
            usage=self.usage,
            finish_reason=self.finish_reason,
            is_mock=self.is_mock,
        )


@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    settings = Settings(_env_file=None, storage_root=tmp_path, mock_llm=True)
    from app.api import uploads

    def configure(config: Settings = settings, client: StaticClient | None = None):
        llm = LLMService(config, client=client) if client is not None else LLMService(config)
        interpretation_service = InterpretationService(llm, config.storage_root)
        planning_service = PlanningService(llm, config.storage_root)
        app.dependency_overrides[get_settings] = lambda: config
        monkeypatch.setattr(uploads, "get_settings", lambda: config)
        app.dependency_overrides[get_interpretation_service] = lambda: interpretation_service
        app.dependency_overrides[get_planning_service] = lambda: planning_service
        return llm

    configure()
    with TestClient(app) as test_client:
        yield test_client, configure, settings
    app.dependency_overrides.clear()


def upload_html(client: TestClient) -> str:
    result = client.post(
        "/api/documents/upload",
        files={"file": ("api-report.html", b"<!doctype html><html><body><h1>Revenue</h1><p>Revenue was $12 million.</p></body></html>", "text/html")},
    )
    assert result.status_code == 201
    return result.json()["id"]


def test_interpretation_create_list_retrieve_reuse_and_persistence(api):
    client, _, settings = api
    document_id = upload_html(client)
    path = f"/api/documents/{document_id}/interpretations"

    created = client.post(path, json={"instructions": "Summarize metrics", "idempotency_key": "interpret-1"})
    assert created.status_code == 201
    body = created.json()
    assert body["interpretation"]["document_id"] == document_id
    assert body["reused"] is False
    assert UUID(body["run_id"])
    assert body["usage"] is None
    assert body["estimated_cost"] is None
    assert body["interpretation"]["provenance"]["is_mock"] is True

    replay = client.post(path, json={"instructions": "Summarize metrics", "idempotency_key": "interpret-1"})
    assert replay.status_code == 200
    assert replay.json()["reused"] is True
    assert replay.json()["run_id"] != body["run_id"]
    assert replay.json()["interpretation"]["interpretation_id"] == body["interpretation"]["interpretation_id"]

    listed = client.get(path)
    assert listed.status_code == 200
    assert listed.json()["count"] == 1
    fetched = client.get(f"{path}/{body['interpretation']['interpretation_id']}")
    assert fetched.status_code == 200
    assert fetched.json() == body["interpretation"]
    other_document_id = upload_html(client)
    assert client.get(
        f"/api/documents/{other_document_id}/interpretations/{body['interpretation']['interpretation_id']}"
    ).status_code == 404
    assert InterpretationStore(settings.storage_root).get_by_id(document_id, body["interpretation"]["interpretation_id"])
    records = list((settings.storage_root / "outputs" / "operations" / document_id).glob("*.json"))
    assert len(records) == 2


def test_interpretation_idempotency_conflicts_and_unknown_resources(api):
    client, _, _ = api
    document_id = upload_html(client)
    path = f"/api/documents/{document_id}/interpretations"
    assert client.post(path, json={"instructions": "First", "idempotency_key": "same-key"}).status_code == 201
    conflict = client.post(path, json={"instructions": "Different", "idempotency_key": "same-key"})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_key_conflict"
    unknown_document = "00000000-0000-4000-8000-000000000099"
    assert client.get(f"/api/documents/{unknown_document}/interpretations").status_code == 404
    assert client.post(f"/api/documents/{unknown_document}/interpretations", json={}).status_code == 404
    assert client.get(f"{path}/00000000-0000-4000-8000-000000000001").status_code == 404
    assert client.get(f"/api/documents/not-a-uuid/interpretations").status_code == 400
    assert client.post(path, json={"unknown": "field"}).status_code == 422


@pytest.mark.parametrize("target_format", ["pptx", "xlsx", "docx", "mmd", "html"])
def test_plan_create_list_retrieve_for_every_target_format(api, target_format):
    client, _, settings = api
    document_id = upload_html(client)
    interpretation_response = client.post(f"/api/documents/{document_id}/interpretations", json={})
    interpretation_id = interpretation_response.json()["interpretation"]["interpretation_id"]
    base = f"/api/documents/{document_id}/interpretations/{interpretation_id}/plans"

    created = client.post(base, json={"target_format": target_format, "idempotency_key": f"plan-{target_format}"})
    assert created.status_code == 201
    payload = created.json()
    assert payload["plan"]["target_format"] == target_format
    assert payload["plan"]["provenance"]["is_mock"] is True
    assert payload["run_id"]
    assert payload["usage"] is None
    replay = client.post(base, json={"target_format": target_format, "idempotency_key": f"plan-{target_format}"})
    assert replay.status_code == 200
    assert replay.json()["reused"] is True

    listed = client.get(base)
    assert listed.status_code == 200
    assert listed.json()["count"] == 1
    by_document = client.get(f"/api/documents/{document_id}/plans")
    assert by_document.json()["count"] == 1
    plan_id = payload["plan"]["plan_id"]
    retrieved = client.get(f"/api/documents/{document_id}/plans/{plan_id}")
    assert retrieved.status_code == 200
    assert retrieved.json() == payload["plan"]
    assert TransformationStore(settings.storage_root).get_by_id(document_id, plan_id)


def test_plan_errors_and_parent_association_are_safe(api):
    client, _, _ = api
    document_id = upload_html(client)
    second_document_id = upload_html(client)
    interpretation_id = client.post(
        f"/api/documents/{document_id}/interpretations", json={}
    ).json()["interpretation"]["interpretation_id"]
    missing = client.post(
        f"/api/documents/{document_id}/interpretations/00000000-0000-4000-8000-000000000001/plans",
        json={"target_format": "pptx"},
    )
    assert missing.status_code == 404
    mismatch = client.post(
        f"/api/documents/{second_document_id}/interpretations/{interpretation_id}/plans",
        json={"target_format": "pptx"},
    )
    assert mismatch.status_code == 404
    plan_path = f"/api/documents/{document_id}/interpretations/{interpretation_id}/plans"
    created_plan = client.post(plan_path, json={"target_format": "pptx", "idempotency_key": "plan-shared-key"})
    assert created_plan.status_code == 201
    assert client.get(
        f"/api/documents/{second_document_id}/plans/{created_plan.json()['plan']['plan_id']}"
    ).status_code == 404
    plan_conflict = client.post(plan_path, json={"target_format": "xlsx", "idempotency_key": "plan-shared-key"})
    assert plan_conflict.status_code == 409
    assert client.post(
        f"/api/documents/{document_id}/interpretations/{interpretation_id}/plans",
        json={"target_format": "pdf"},
    ).status_code == 422


def test_concurrent_identical_requests_share_persisted_result(api):
    client, _, _ = api
    document_id = upload_html(client)
    path = f"/api/documents/{document_id}/interpretations"

    def make_request(_):
        return client.post(path, json={"instructions": "Same input"})

    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(executor.map(make_request, range(4)))
    assert all(response.status_code in {200, 201} for response in responses)
    ids = {response.json()["interpretation"]["interpretation_id"] for response in responses}
    assert len(ids) == 1
    assert sum(not response.json()["reused"] for response in responses) == 1


def test_token_usage_cost_and_request_id_validation(api):
    client, configure, original_settings = api
    document_id = upload_html(client)
    usage = LLMTokenUsage(prompt_tokens=100, completion_tokens=40, total_tokens=140)
    provider = StaticClient(is_mock=False, usage=usage)
    priced = Settings(
        _env_file=None,
        storage_root=original_settings.storage_root,
        mock_llm=False,
        llm_base_url="https://example.test/v1",
        llm_model="api-test-model",
        llm_input_cost_per_million_tokens="2.0",
        llm_output_cost_per_million_tokens="8.0",
        llm_pricing_version="test-2026-01",
    )
    configure(priced, provider)
    response = client.post(
        f"/api/documents/{document_id}/interpretations",
        json={},
        headers={"X-Request-ID": "bad request id"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["usage"] == {"input_tokens": 100, "output_tokens": 40, "total_tokens": 140}
    assert Decimal(str(body["estimated_cost"])) == Decimal("0.00052")
    assert body["pricing"]["pricing_version"] == "test-2026-01"
    assert UUID(response.headers["x-request-id"])
    assert body["run_id"]
    operation_files = list((priced.storage_root / "outputs" / "operations" / document_id).glob("*.json"))
    assert len(operation_files) == 1


def test_provider_error_has_safe_structured_api_response(api, monkeypatch):
    client, configure, original_settings = api
    document_id = upload_html(client)
    provider = StaticClient(is_mock=False, error=LLMProviderError(503))
    settings = Settings(
        _env_file=None,
        storage_root=original_settings.storage_root,
        mock_llm=False,
        llm_base_url="https://example.test/v1",
        llm_model="api-test-model",
        llm_api_key="do-not-return-this-secret",
        llm_max_attempts=2,
    )
    configure(settings, provider)
    async def no_wait(_):
        return None
    monkeypatch.setattr("app.services.llm.asyncio.sleep", no_wait)

    response = client.post(f"/api/documents/{document_id}/interpretations", json={})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "llm_unavailable"
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
    assert "do-not-return-this-secret" not in response.text
    assert "sensitive provider body" not in response.text
    assert provider.calls == 2
    records = list((settings.storage_root / "outputs" / "operations" / document_id).glob("*.json"))
    assert len(records) == 1
    import json
    assert json.loads(records[0].read_text(encoding="utf-8"))["status"] == "failed"


@pytest.mark.parametrize(
    ("kind", "expected_code", "expected_message"),
    [
        ("tpm", "llm_rate_limit_tpm", "per-minute token"),
        ("tpd", "llm_rate_limit_tpd", "daily token"),
        ("rpm", "llm_rate_limit_rpm", "per-minute request"),
        ("rpd", "llm_rate_limit_rpd", "daily request"),
        ("quota", "llm_quota_exhausted", "billing limit"),
    ],
)
def test_rate_limit_scope_has_safe_structured_api_error(api, kind, expected_code, expected_message):
    client, configure, original_settings = api
    document_id = upload_html(client)
    provider = StaticClient(
        is_mock=False,
        error=LLMProviderError(
            429,
            retry_after_seconds=22,
            rate_limit_kind=kind,
            provider_error_message="private provider response must not be returned",
            retryable=kind in {"tpm", "rpm"},
        ),
    )
    settings = Settings(
        _env_file=None,
        storage_root=original_settings.storage_root,
        mock_llm=False,
        llm_base_url="https://example.test/v1",
        llm_model="api-test-model",
        llm_max_attempts=1,
    )
    configure(settings, provider)
    response = client.post(f"/api/documents/{document_id}/interpretations", json={})
    payload = response.json()["error"]
    assert response.status_code == 429
    assert payload["code"] == expected_code
    assert expected_message in payload["message"].lower()
    assert payload["details"]["rate_limit_kind"] == kind
    assert payload["details"]["retry_after_seconds"] == 22
    assert "private provider response" not in response.text
    assert provider.calls == 1


@pytest.mark.parametrize(
    ("kind", "expected_code"),
    [
        ("tpm", "provider_rate_limit_tpm"),
        ("tpd", "provider_rate_limit_tpd"),
        ("rpm", "provider_rate_limit_rpm"),
        ("rpd", "provider_rate_limit_rpd"),
        ("quota", "provider_quota_exhausted"),
    ],
)
def test_workflow_error_code_preserves_rate_limit_scope(kind, expected_code):
    error = LLMProviderError(429, rate_limit_kind=kind, retryable=kind in {"tpm", "rpm"})
    code, message = WorkflowExecutor._safe_error(error)
    assert code == expected_code
    assert message


def test_provider_413_has_safe_actionable_api_error(api):
    client, configure, original_settings = api
    document_id = upload_html(client)
    provider = StaticClient(
        is_mock=False,
        error=LLMProviderError(
            413,
            provider_error_code="request_too_large",
            provider_error_message="private body detail",
            retryable=False,
        ),
    )
    settings = Settings(
        _env_file=None,
        storage_root=original_settings.storage_root,
        mock_llm=False,
        llm_base_url="https://example.test/v1",
        llm_model="api-test-model",
        llm_max_attempts=3,
    )
    configure(settings, provider)
    response = client.post(f"/api/documents/{document_id}/interpretations", json={})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "llm_request_too_large"
    assert response.json()["error"]["details"] == {"provider_status": 413, "retryable": False}
    assert "private body detail" not in response.text
    assert provider.calls == 1


def test_malformed_provider_json_maps_to_502_without_retry_and_logs_before_response(api, caplog):
    client, configure, original_settings = api
    document_id = upload_html(client)
    provider = StaticClient(
        is_mock=False,
        content="private malformed payload",
        usage=LLMTokenUsage(prompt_tokens=90, completion_tokens=25, total_tokens=115),
    )
    settings = Settings(
        _env_file=None,
        storage_root=original_settings.storage_root,
        mock_llm=False,
        llm_base_url="https://example.test/v1",
        llm_model="api-test-model",
        llm_max_attempts=3,
    )
    configure(settings, provider)
    response = client.post(f"/api/documents/{document_id}/interpretations", json={})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "invalid_provider_output"
    assert "private malformed payload" not in response.text
    assert provider.calls == 1
    detailed = next(
        record for record in caplog.records
        if record.msg == "interpretation_response_validation_failed"
    )
    assert detailed.error_category == "semantic_json_parse"
    assert detailed.exception_class == "InvalidInterpretationResponseError"
    assert detailed.json_parsing_succeeded is False
    assert detailed.token_usage["total_tokens"] == 115
    operation_failed = next(
        record for record in caplog.records
        if record.msg == "interpretation_operation_failed"
    )
    assert operation_failed.token_usage_present is True
    assert caplog.records.index(detailed) < caplog.records.index(operation_failed)
    import json
    operation_file = next((settings.storage_root / "outputs" / "operations" / document_id).glob("*.json"))
    operation = json.loads(operation_file.read_text(encoding="utf-8"))
    assert operation["status"] == "failed"
    assert operation["usage"] == {"input_tokens": 90, "output_tokens": 25, "total_tokens": 115}


def test_llm_client_invalid_response_preserves_usage_in_failed_operation_record(api):
    client, configure, original_settings = api
    document_id = upload_html(client)
    usage = LLMTokenUsage(prompt_tokens=3482, completion_tokens=2600, total_tokens=6082)
    provider = StaticClient(
        is_mock=False,
        error=LLMInvalidResponseError(
            "The provider response is invalid.",
            failure_phase="completion_payload_validation",
            failure_reason="message_missing_or_invalid",
            operation_usage=usage,
        ),
    )
    settings = Settings(
        _env_file=None,
        storage_root=original_settings.storage_root,
        mock_llm=False,
        llm_base_url="https://example.test/v1",
        llm_model="api-test-model",
    )
    configure(settings, provider)

    response = client.post(f"/api/documents/{document_id}/interpretations", json={})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "llm_invalid_response"
    import json
    operation_file = next((settings.storage_root / "outputs" / "operations" / document_id).glob("*.json"))
    operation = json.loads(operation_file.read_text(encoding="utf-8"))
    assert operation["usage"] == {"input_tokens": 3482, "output_tokens": 2600, "total_tokens": 6082}


def test_length_truncated_completion_has_clear_safe_api_error(api):
    client, configure, original_settings = api
    document_id = upload_html(client)
    provider = StaticClient(
        is_mock=False,
        content='{"summary":"incomplete',
        finish_reason="length",
        usage=LLMTokenUsage(prompt_tokens=3492, completion_tokens=3072, total_tokens=6564),
    )
    settings = Settings(
        _env_file=None,
        storage_root=original_settings.storage_root,
        mock_llm=False,
        llm_base_url="https://example.test/v1",
        llm_model="api-test-model",
    )
    configure(settings, provider)

    response = client.post(f"/api/documents/{document_id}/interpretations", json={})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "llm_output_truncated"
    assert "truncated" in response.json()["error"]["message"].lower()
    assert "incomplete" not in response.text
    assert provider.calls == 1
    import json
    operation_file = next((settings.storage_root / "outputs" / "operations" / document_id).glob("*.json"))
    operation = json.loads(operation_file.read_text(encoding="utf-8"))
    assert operation["status"] == "failed"
    assert operation["usage"] == {"input_tokens": 3492, "output_tokens": 3072, "total_tokens": 6564}


def test_unknown_pricing_returns_null_cost_with_usage():
    settings = Settings(_env_file=None)
    usage = LLMTokenUsage(prompt_tokens=11, completion_tokens=7, total_tokens=18)
    summary, cost = usage_and_cost(settings, usage)
    assert summary.input_tokens == 11
    assert summary.output_tokens == 7
    assert cost.estimated_cost_usd is None


def test_json_logs_receive_request_run_and_operation_context():
    import json
    import logging

    record = logging.LogRecord("test", logging.INFO, __file__, 1, "operation_started", (), None)
    with log_context(request_id="req-1", run_id="run-1", document_id="doc-1", operation="planning"):
        payload = json.loads(JsonFormatter().format(record))
    assert payload["svc"] == "kiln"
    assert payload["request_id"] == "req-1"
    assert payload["run_id"] == "run-1"
    assert payload["document_id"] == "doc-1"
    assert payload["operation"] == "planning"
    with log_context(request_id="req-2", run_id="run-2", document_id="doc-2", node_id="node-2"):
        node_payload = json.loads(JsonFormatter().format(record))
    assert node_payload["node_id"] == "node-2"


def test_mock_transformations_render_and_download_native_html_docx_and_pptx(api):
    client, _, _ = api
    document_id = upload_html(client)
    interpretation_response = client.post(f"/api/documents/{document_id}/interpretations", json={})
    assert interpretation_response.status_code == 201

    html_response = client.post(
        f"/api/documents/{document_id}/transformations",
        json={"target_format": "html"},
    )
    assert html_response.status_code == 201
    html_body = html_response.json()
    assert html_body["output"]["target_format"] == "html"
    assert html_body["output"]["is_mock"] is True
    assert html_body["output"]["output_id"]
    assert html_body["output"]["filename"].endswith(".html")
    assert UUID(html_body["run_id"])
    html_download = client.get(html_body["download_url"])
    assert html_download.status_code == 200
    html = BeautifulSoup(html_download.content, "html.parser")
    assert html.title is not None
    assert "Revenue was $12 million." in html.get_text()
    assert "MOCK OUTPUT" in html.get_text()
    repeat_html = client.post(
        f"/api/documents/{document_id}/transformations",
        json={"target_format": "html"},
    )
    assert repeat_html.status_code == 201
    assert client.get(repeat_html.json()["download_url"]).content == html_download.content

    docx_response = client.post(
        f"/api/documents/{document_id}/transformations",
        json={"target_format": "docx"},
    )
    assert docx_response.status_code == 201
    docx_body = docx_response.json()
    assert docx_body["output"]["target_format"] == "docx"
    assert docx_body["output"]["is_mock"] is True
    docx_download = client.get(docx_body["download_url"])
    assert docx_download.status_code == 200
    document = WordDocument(BytesIO(docx_download.content))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "Revenue was $12 million." in text
    assert "MOCK OUTPUT" in text

    pptx_response = client.post(
        f"/api/documents/{document_id}/transformations",
        json={"target_format": "pptx"},
    )
    assert pptx_response.status_code == 201, pptx_response.text
    pptx_body = pptx_response.json()
    assert pptx_body["output"]["target_format"] == "pptx"
    assert pptx_body["output"]["is_mock"] is True
    pptx_download = client.get(pptx_body["download_url"])
    assert pptx_download.status_code == 200
    assert pptx_download.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )
    presentation = Presentation(BytesIO(pptx_download.content))
    assert len(presentation.slides) >= 1
    pptx_text = "\n".join(
        shape.text
        for slide in presentation.slides
        for shape in slide.shapes
        if shape.has_text_frame
    )
    assert "Revenue was $12 million." in pptx_text
    assert "MOCK OUTPUT" in pptx_text


def test_configured_llm_generates_valid_cited_html_artifact(api):
    client, configure, original_settings = api
    document_id = upload_html(client)
    ir = client.get(f"/api/documents/{document_id}/ir").json()

    def find_text_block(sections):
        for section in sections:
            for block in section["blocks"]:
                if block["kind"] == "text":
                    return section, block
            found = find_text_block(section["children"])
            if found is not None:
                return found
        return None

    source_section, source_block = find_text_block(ir["sections"])
    reference = {
        "block_id": source_block["id"],
        "section_id": source_section["id"],
        "source_location": source_block["source"],
    }
    provider = StaticClient(
        is_mock=False,
        usage=LLMTokenUsage(prompt_tokens=120, completion_tokens=80, total_tokens=200),
        content=json.dumps({
            "summary": "The report states revenue of $12 million.",
            "facts": [],
            "metrics": [],
            "entities": [],
            "claims": [],
            "relationships": [],
            "insights": [],
            "warnings": [],
        }),
    )
    settings = Settings(
        _env_file=None,
        storage_root=original_settings.storage_root,
        mock_llm=False,
        llm_base_url="https://example.test/v1",
        llm_model="artifact-test-model",
    )
    configure(settings, provider)
    interpretation = client.post(f"/api/documents/{document_id}/interpretations", json={})
    assert interpretation.status_code == 201

    provider.content = json.dumps({
        "target_format": "html",
        "page_title": "Revenue Brief",
        "sections": [{
            "heading": "Revenue",
            "paragraphs": [{"text": "Revenue was $12 million.", "source_references": [reference]}],
            "bullet_points": [],
            "metrics": [],
            "tables": [],
        }],
    })
    response = client.post(
        f"/api/documents/{document_id}/transformations",
        json={"target_format": "html", "instructions": "Create a concise financial brief."},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["output"]["is_mock"] is False
    assert body["usage"] == {"input_tokens": 120, "output_tokens": 80, "total_tokens": 200}
    assert provider.calls == 2
    assert client.get(body["download_url"]).status_code == 200


def test_configured_llm_generates_valid_cited_pptx_artifact(api):
    client, configure, original_settings = api
    document_id = upload_html(client)
    ir = client.get(f"/api/documents/{document_id}/ir").json()

    def find_text_block(sections):
        for section in sections:
            for block in section["blocks"]:
                if block["kind"] == "text":
                    return section, block
            found = find_text_block(section["children"])
            if found is not None:
                return found
        return None

    source_section, source_block = find_text_block(ir["sections"])
    reference = {
        "block_id": source_block["id"],
        "section_id": source_section["id"],
        "source_location": source_block["source"],
    }
    provider = StaticClient(
        is_mock=False,
        usage=LLMTokenUsage(prompt_tokens=120, completion_tokens=80, total_tokens=200),
        content=json.dumps({
            "summary": "The report states revenue of $12 million.",
            "facts": [], "metrics": [], "entities": [], "claims": [],
            "relationships": [], "insights": [], "warnings": [],
        }),
    )
    configure(Settings(
        _env_file=None,
        storage_root=original_settings.storage_root,
        mock_llm=False,
        llm_base_url="https://example.test/v1",
        llm_model="artifact-test-model",
    ), provider)
    assert client.post(f"/api/documents/{document_id}/interpretations", json={}).status_code == 201
    pptx_content = {
        "target_format": "pptx",
        "presentation_title": "Revenue Brief",
        "slides": [{
            "slide_id": "slide-revenue",
            "title": "Revenue",
            "purpose": "Summarize the reported revenue result.",
            "visual_guidance": "Keep the slide simple and emphasize the reported amount.",
            "title_source_references": [reference],
            "elements": [{
                "element_id": "element-revenue-chart",
                "element_type": "chart",
                "content": {
                    "title": "Revenue by quarter",
                    "chart_type": "bar",
                    "categories": ["Q1", "Q2", "Q3"],
                    "series": [{"name": "Revenue", "values": [10, 11, 12]}],
                    "source_references": [reference],
                },
            }],
        }],
    }
    provider.content = json.dumps(pptx_content)
    response = client.post(
        f"/api/documents/{document_id}/transformations",
        json={"target_format": "pptx", "instructions": "Create a concise revenue deck."},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["output"]["is_mock"] is False
    assert body["output"]["artifact_schema_version"] == "1.2"
    assert body["usage"] == {"input_tokens": 120, "output_tokens": 80, "total_tokens": 200}
    downloaded = client.get(body["download_url"])
    assert downloaded.status_code == 200
    presentation = Presentation(BytesIO(downloaded.content))
    slide = presentation.slides[0]
    chart_shape = next(shape for shape in slide.shapes if shape.has_chart)
    assert chart_shape.chart.chart_title.text_frame.text == "Revenue by quarter"
    assert chart_shape.chart.series[0].name == "Revenue"
    assert list(chart_shape.chart.series[0].values) == [10.0, 11.0, 12.0]
    notes = slide.notes_slide.notes_text_frame.text
    assert '"block_id"' in notes
    assert "Summarize the reported revenue result." in notes
    assert "Keep the slide simple and emphasize the reported amount." in notes

    invalid_content = {**pptx_content, "undeclared_contract_field": "private fixture value"}
    provider.content = json.dumps(invalid_content)
    invalid = client.post(
        f"/api/documents/{document_id}/transformations",
        json={"target_format": "pptx", "instructions": "Create a concise revenue deck."},
    )
    assert invalid.status_code == 502
    error = invalid.json()["error"]
    assert error["code"] == "invalid_artifact_output"
    diagnostics = error["details"]
    assert diagnostics["target_format"] == "pptx"
    assert diagnostics["schema_model"] == "PPTXArtifactContent"
    assert diagnostics["prompt_version"] == "artifact_v8"
    assert diagnostics["artifact_schema_version"] == "1.2"
    assert diagnostics["json_parsing_succeeded"] is True
    assert any(
        item["field_path"] == ["undeclared_contract_field"]
        and item["category"] == "undeclared_field"
        for item in diagnostics["validation_errors"]
    )
    assert "private fixture value" not in invalid.text


def test_native_ir_targets_require_existing_interpretation(api):
    client, _, _ = api
    document_id = upload_html(client)
    xlsx = client.post(
        f"/api/documents/{document_id}/transformations",
        json={"target_format": "xlsx"},
    )
    assert xlsx.status_code == 409
    assert xlsx.json()["error"]["code"] == "interpretation_required"

    missing = client.post(
        f"/api/documents/{document_id}/transformations",
        json={"target_format": "docx"},
    )
    assert missing.status_code == 409
    assert missing.json()["error"]["code"] == "interpretation_required"


def test_xlsx_and_mmd_native_ir_artifacts_download_without_llm_generation(api):
    client, _, _ = api
    document_id = upload_html(client)
    interpretation = client.post(f"/api/documents/{document_id}/interpretations", json={})
    assert interpretation.status_code == 201

    xlsx_response = client.post(
        f"/api/documents/{document_id}/transformations",
        json={"target_format": "xlsx"},
    )
    assert xlsx_response.status_code == 201, xlsx_response.text
    xlsx_body = xlsx_response.json()
    assert xlsx_body["output"]["provider"] == "native_ir"
    assert xlsx_body["output"]["model"] == "deterministic-writer"
    assert xlsx_body["output"]["is_mock"] is False
    assert xlsx_body["output"]["filename"].endswith(".xlsx")
    assert xlsx_body["usage"] is None
    xlsx_download = client.get(xlsx_body["download_url"])
    assert xlsx_download.status_code == 200
    assert xlsx_download.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    workbook = load_workbook(BytesIO(xlsx_download.content), data_only=False)
    assert "Document" in workbook.sheetnames
    assert "IR Content" in workbook.sheetnames
    workbook.close()

    mmd_response = client.post(
        f"/api/documents/{document_id}/transformations",
        json={"target_format": "mmd"},
    )
    assert mmd_response.status_code == 201, mmd_response.text
    mmd_body = mmd_response.json()
    assert mmd_body["output"]["provider"] == "native_ir"
    assert mmd_body["output"]["is_mock"] is False
    assert mmd_body["output"]["filename"].endswith(".mmd")
    assert mmd_body["usage"] is None
    mmd_download = client.get(mmd_body["download_url"])
    assert mmd_download.status_code == 200
    assert mmd_download.headers["content-type"].startswith("text/plain")
    assert mmd_download.content.startswith(b"flowchart TD")


def test_workflow_dag_executes_html_to_interpretation_plan_docx_and_download(api):
    client, _, _ = api
    document_id = upload_html(client)
    definition = client.post("/api/workflows", json={
        "name": "HTML to Word",
        "nodes": [
            {"id": "source", "kind": "source", "document_id": document_id, "source_format": "html"},
            {"id": "interpret", "kind": "interpretation"},
            {"id": "plan", "kind": "planning", "target_format": "docx"},
            {"id": "render", "kind": "transformation", "target_format": "docx"},
            {"id": "output", "kind": "output"},
        ],
        "edges": [
            {"source": "source", "target": "interpret"},
            {"source": "interpret", "target": "plan"},
            {"source": "plan", "target": "render"},
            {"source": "render", "target": "output"},
        ],
    })
    assert definition.status_code == 201, definition.text
    workflow_id = definition.json()["id"]

    queued = client.post(f"/api/workflows/{workflow_id}/runs", json={})
    assert queued.status_code == 202, queued.text
    run_id = queued.json()["run_id"]
    assert UUID(run_id)

    run_response = client.get(f"/api/workflows/{workflow_id}/runs/{run_id}")
    assert run_response.status_code == 200
    run = run_response.json()
    assert run["status"] == "done"
    assert [run["node_results"][node]["status"] for node in ("source", "interpret", "plan", "render", "output")] == ["done"] * 5
    assert len(run["final_outputs"]) == 1
    assert run["final_outputs"][0]["download_url"].endswith("/download")
    assert run["final_outputs"][0]["output"]["target_format"] == "docx"
    output_result = run["node_results"]["output"]
    assert output_result["output"]["target_format"] == "docx"
    assert output_result["download_url"].endswith("/download")

    downloaded = client.get(output_result["download_url"])
    assert downloaded.status_code == 200
    document = WordDocument(BytesIO(downloaded.content))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "Revenue was $12 million." in text
    assert "MOCK OUTPUT" in text

    events = client.get(f"/api/events/workflows/{workflow_id}/runs/{run_id}")
    assert events.status_code == 200
    assert "event: node_completed" in events.text
    assert "event: run_completed" in events.text


def test_truncated_planning_recovery_never_reaches_native_writer(api, monkeypatch):
    client, configure, default_settings = api
    document_id = upload_html(client)
    requests = []
    writer_calls = []

    async def no_wait(_delay: float) -> None:
        return None

    monkeypatch.setattr("app.services.llm_client.asyncio.sleep", no_wait)

    def provider_handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            content = json.dumps({
                "summary": "The source contains revenue information.",
                "facts": [], "metrics": [], "entities": [], "claims": [],
                "relationships": [], "insights": [], "warnings": [],
            })
            finish_reason = "stop"
        else:
            content = '{"target_format":"docx","output_structure":'
            finish_reason = "length"
        return httpx.Response(200, json={
            "model": "openai/gpt-oss-20b",
            "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200},
        })

    provider = OpenAICompatibleClient(
        base_url="https://api.groq.com/openai/v1",
        model="openai/gpt-oss-20b",
        api_key="test-only-key",
        transport=httpx.MockTransport(provider_handler),
    )
    configure(Settings(
        _env_file=None,
        storage_root=default_settings.storage_root,
        mock_llm=False,
        llm_base_url="https://api.groq.com/openai/v1",
        llm_api_key="test-only-key",
        llm_model="openai/gpt-oss-20b",
    ), provider)

    class WriterSpy:
        def __init__(self, *_args, **_kwargs):
            pass

        async def transform(self, *_args, **_kwargs):
            writer_calls.append(True)

    monkeypatch.setattr("app.orchestration.engine.ArtifactTransformationService", WriterSpy)
    definition = client.post("/api/workflows", json={
        "name": "Truncated planning must block rendering",
        "nodes": [
            {"id": "source", "kind": "source", "document_id": document_id, "source_format": "html"},
            {"id": "interpret", "kind": "interpretation"},
            {"id": "plan", "kind": "planning", "target_format": "docx"},
            {"id": "render", "kind": "transformation", "target_format": "docx"},
            {"id": "output", "kind": "output"},
        ],
        "edges": [
            {"source": "source", "target": "interpret"},
            {"source": "interpret", "target": "plan"},
            {"source": "plan", "target": "render"},
            {"source": "render", "target": "output"},
        ],
    })
    assert definition.status_code == 201, definition.text
    workflow_id = definition.json()["id"]
    queued = client.post(f"/api/workflows/{workflow_id}/runs", json={})
    assert queued.status_code == 202, queued.text
    run = client.get(f"/api/workflows/{workflow_id}/runs/{queued.json()['run_id']}").json()

    assert run["status"] == "failed"
    assert run["node_results"]["interpret"]["status"] == "done"
    assert run["node_results"]["plan"]["status"] == "failed"
    assert run["node_results"]["plan"]["error_code"] == "llm_output_truncated"
    assert run["node_results"]["plan"]["usage"] == {
        "prompt_tokens": 200,
        "completion_tokens": 200,
        "total_tokens": 400,
    }
    assert run["node_results"]["render"]["status"] == "blocked"
    assert run["node_results"]["output"]["status"] == "blocked"
    assert len(requests) == 3  # interpretation, initial planning, one recovery
    assert writer_calls == []


def test_workflow_interpretation_requests_4096_completion_tokens(api, monkeypatch):
    client, _, _ = api
    requested_budgets = []
    original_complete = LLMService.complete

    async def record_budget(self, messages, *, max_completion_tokens=None):
        requested_budgets.append(max_completion_tokens)
        return await original_complete(self, messages, max_completion_tokens=max_completion_tokens)

    monkeypatch.setattr(LLMService, "complete", record_budget)
    document_id = upload_html(client)
    definition = client.post("/api/workflows", json={
        "name": "Workflow interpretation budget",
        "nodes": [
            {"id": "source", "kind": "source", "document_id": document_id, "source_format": "html"},
            {"id": "interpret", "kind": "interpretation"},
            {"id": "plan", "kind": "planning", "target_format": "docx"},
            {"id": "transform", "kind": "transformation", "target_format": "docx"},
            {"id": "output", "kind": "output"},
        ],
        "edges": [
            {"source": "source", "target": "interpret"},
            {"source": "interpret", "target": "plan"},
            {"source": "plan", "target": "transform"},
            {"source": "transform", "target": "output"},
        ],
    })
    assert definition.status_code == 201, definition.text
    workflow_id = definition.json()["id"]
    queued = client.post(f"/api/workflows/{workflow_id}/runs", json={})
    assert queued.status_code == 202, queued.text

    run = client.get(f"/api/workflows/{workflow_id}/runs/{queued.json()['run_id']}").json()
    assert run["status"] == "done"
    assert all(
        run["node_results"][node_id]["status"] == "done"
        for node_id in ("source", "interpret", "plan", "transform", "output")
    )
    assert requested_budgets == [4096]


def test_workflow_planning_sends_bounded_completion_budget_to_provider(api, monkeypatch):
    client, configure, default_settings = api
    document_id = upload_html(client)
    request_bodies = []
    waits = []

    async def no_wait(delay: float) -> None:
        waits.append(delay)

    monkeypatch.setattr("app.services.llm_client.asyncio.sleep", no_wait)

    semantic_response = json.dumps({
        "summary": "The uploaded report contains revenue information.",
        "facts": [],
        "metrics": [],
        "entities": [],
        "claims": [],
        "relationships": [],
        "insights": [],
        "warnings": [],
    })

    def provider_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        request_bodies.append(body)
        content = semantic_response if len(request_bodies) == 1 else "{}"
        return httpx.Response(
            200,
            headers=(
                {
                    "x-ratelimit-remaining-tokens": "1333",
                    "x-ratelimit-reset-tokens": "50s",
                }
                if len(request_bodies) == 1 else {}
            ),
            json={
                "model": "openai/gpt-oss-20b",
                "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            },
        )

    provider = OpenAICompatibleClient(
        base_url="https://api.groq.com/openai/v1",
        model="openai/gpt-oss-20b",
        api_key="test-only-key",
        transport=httpx.MockTransport(provider_handler),
    )
    provider_settings = Settings(
        _env_file=None,
        storage_root=default_settings.storage_root,
        mock_llm=False,
        llm_base_url="https://api.groq.com/openai/v1",
        llm_api_key="test-only-key",
        llm_model="openai/gpt-oss-20b",
    )
    configure(provider_settings, provider)

    definition = client.post("/api/workflows", json={
        "name": "Workflow planning completion budget",
        "nodes": [
            {"id": "source", "kind": "source", "document_id": document_id, "source_format": "html"},
            {"id": "interpret", "kind": "interpretation"},
            {"id": "plan", "kind": "planning", "target_format": "docx"},
            {"id": "transform", "kind": "transformation", "target_format": "docx"},
            {"id": "output", "kind": "output"},
        ],
        "edges": [
            {"source": "source", "target": "interpret"},
            {"source": "interpret", "target": "plan"},
            {"source": "plan", "target": "transform"},
            {"source": "transform", "target": "output"},
        ],
    })
    assert definition.status_code == 201, definition.text
    workflow_id = definition.json()["id"]
    queued = client.post(f"/api/workflows/{workflow_id}/runs", json={})
    assert queued.status_code == 202, queued.text

    run = client.get(f"/api/workflows/{workflow_id}/runs/{queued.json()['run_id']}").json()
    assert run["status"] == "failed"
    assert run["node_results"]["source"]["status"] == "done"
    assert run["node_results"]["interpret"]["status"] == "done"
    assert run["node_results"]["plan"]["status"] == "failed"
    assert run["node_results"]["transform"]["status"] == "blocked"
    assert run["node_results"]["output"]["status"] == "blocked"
    assert len(request_bodies) == 2

    interpretation_prompt_bytes = sum(
        len(message["content"].encode("utf-8")) for message in request_bodies[0]["messages"]
    )
    interpretation_estimate = provider._estimate_groq_prompt_tokens(interpretation_prompt_bytes)
    expected_interpretation_budget = min(
        4096,
        provider.GROQ_TPM_LIMIT
        - interpretation_estimate
        - provider.GROQ_PROMPT_ESTIMATE_SAFETY_TOKENS,
    )
    assert request_bodies[0]["max_completion_tokens"] == expected_interpretation_budget

    planning_request = request_bodies[1]
    planning_prompt_bytes = sum(
        len(message["content"].encode("utf-8")) for message in planning_request["messages"]
    )
    estimated_prompt_tokens = provider._estimate_groq_prompt_tokens(planning_prompt_bytes)
    expected_budget = min(
        4096,
        provider.GROQ_TPM_LIMIT
        - estimated_prompt_tokens
        - provider.GROQ_PROMPT_ESTIMATE_SAFETY_TOKENS,
    )
    assert 2048 < expected_budget <= 4096
    assert planning_request["max_completion_tokens"] == expected_budget
    assert "max_tokens" not in planning_request
    assert waits and waits[0] >= 49.9


def test_workflow_dag_executes_html_to_pptx_and_download(api):
    client, _, _ = api
    document_id = upload_html(client)
    definition = client.post("/api/workflows", json={
        "name": "HTML to PowerPoint",
        "nodes": [
            {"id": "source", "kind": "source", "document_id": document_id, "source_format": "html"},
            {"id": "interpret", "kind": "interpretation"},
            {"id": "plan", "kind": "planning", "target_format": "pptx"},
            {"id": "render", "kind": "transformation", "target_format": "pptx"},
            {"id": "output", "kind": "output"},
        ],
        "edges": [
            {"source": "source", "target": "interpret"},
            {"source": "interpret", "target": "plan"},
            {"source": "plan", "target": "render"},
            {"source": "render", "target": "output"},
        ],
    })
    assert definition.status_code == 201, definition.text
    workflow_id = definition.json()["id"]
    queued = client.post(f"/api/workflows/{workflow_id}/runs", json={})
    assert queued.status_code == 202, queued.text
    run_id = queued.json()["run_id"]
    run = client.get(f"/api/workflows/{workflow_id}/runs/{run_id}").json()
    assert run["status"] == "done"
    assert all(run["node_results"][node]["status"] == "done" for node in ("source", "interpret", "plan", "render", "output"))
    output = run["node_results"]["output"]
    assert output["output"]["target_format"] == "pptx"
    downloaded = client.get(output["download_url"])
    assert downloaded.status_code == 200
    presentation = Presentation(BytesIO(downloaded.content))
    assert len(presentation.slides) > 0
    rendered_text = "\n".join(
        shape.text
        for slide in presentation.slides
        for shape in slide.shapes
        if shape.has_text_frame
    )
    assert "Revenue was $12 million." in rendered_text


def test_workflow_dag_detects_cycles_and_incompatible_edges(api):
    client, _, _ = api
    document_id = upload_html(client)
    nodes = [
        {"id": "source", "kind": "source", "document_id": document_id},
        {"id": "interpret", "kind": "interpretation"},
        {"id": "render", "kind": "transformation", "target_format": "docx"},
        {"id": "output", "kind": "output"},
    ]
    cyclic = client.post("/api/workflows", json={
        "nodes": nodes,
        "edges": [
            {"source": "source", "target": "interpret"},
            {"source": "interpret", "target": "render"},
            {"source": "render", "target": "output"},
            {"source": "output", "target": "source"},
        ],
    })
    assert cyclic.status_code == 422
    assert "cycle" in cyclic.json()["error"]["message"].lower()

    incompatible = client.post("/api/workflows", json={
        "nodes": nodes,
        "edges": [
            {"source": "source", "target": "interpret"},
            {"source": "interpret", "target": "output"},
        ],
    })
    assert incompatible.status_code == 422
    assert incompatible.json()["error"]["code"] == "invalid_workflow"


def test_workflow_branch_failure_blocks_only_its_downstream_output(api):
    client, configure, original_settings = api
    document_id = upload_html(client)
    ir = client.get(f"/api/documents/{document_id}/ir").json()

    def find_text_block(sections):
        for section in sections:
            for block in section["blocks"]:
                if block["kind"] == "text":
                    return section, block
            found = find_text_block(section["children"])
            if found is not None:
                return found
        return None

    source_section, source_block = find_text_block(ir["sections"])
    reference = {
        "block_id": source_block["id"],
        "section_id": source_section["id"],
        "source_location": source_block["source"],
    }

    class BranchProvider:
        def __init__(self):
            self.calls = 0

        async def complete(self, messages):
            self.calls += 1
            if self.calls == 1:
                content = {
                    "summary": "The report states revenue of $12 million.",
                    "facts": [], "metrics": [], "entities": [], "claims": [],
                    "relationships": [], "insights": [], "warnings": [],
                }
            else:
                content = {
                    "target_format": "html",
                    "page_title": "Revenue",
                    "sections": [{
                        "heading": "Revenue",
                        "paragraphs": [{
                            "text": "Revenue was $12 million.",
                            "source_references": [reference],
                        }],
                    }],
                }
            return LLMCompletionResult(
                content=json.dumps(content),
                model="branch-test-model",
                provider="branch-test-provider",
                usage=LLMTokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                is_mock=False,
            )

    provider = BranchProvider()
    configure(Settings(
        _env_file=None,
        storage_root=original_settings.storage_root,
        mock_llm=False,
        llm_base_url="https://example.test/v1",
        llm_model="branch-test-model",
    ), provider)

    definition = client.post("/api/workflows", json={
        "name": "Branch validation",
        "nodes": [
            {"id": "source", "kind": "source", "document_id": document_id},
            {"id": "interpret", "kind": "interpretation"},
            {"id": "good", "kind": "transformation", "target_format": "html"},
            {"id": "good-output", "kind": "output"},
            {
                "id": "unsupported",
                "kind": "transformation",
                "target_format": "xlsx",
                "instruction": "Add a calculated forecast that requires an AI transformation.",
            },
            {"id": "unsupported-output", "kind": "output"},
        ],
        "edges": [
            {"source": "source", "target": "interpret"},
            {"source": "interpret", "target": "good"},
            {"source": "good", "target": "good-output"},
            {"source": "interpret", "target": "unsupported"},
            {"source": "unsupported", "target": "unsupported-output"},
        ],
    })
    assert definition.status_code == 201, definition.text
    workflow_id = definition.json()["id"]
    queued = client.post(f"/api/workflows/{workflow_id}/runs", json={})
    run = client.get(f"/api/workflows/{workflow_id}/runs/{queued.json()['run_id']}").json()
    assert run["status"] == "failed"
    assert run["node_results"]["source"]["status"] == "done"
    assert run["node_results"]["interpret"]["status"] == "done"
    assert run["node_results"]["good"]["status"] == "done"
    assert run["node_results"]["good-output"]["status"] == "done"
    assert run["node_results"]["unsupported"]["status"] == "failed"
    assert run["node_results"]["unsupported"]["error_code"] == "unsupported_ir_content"
    assert run["node_results"]["unsupported-output"]["status"] == "blocked"
    # One interpretation and one supported HTML artifact request; the deterministic
    # XLSX writer refuses the instruction without issuing a third provider request.
    assert provider.calls == 2
