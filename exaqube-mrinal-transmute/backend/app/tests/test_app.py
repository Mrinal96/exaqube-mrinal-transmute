from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app, settings as app_settings


def test_health_endpoint_reports_unconfigured_llm(monkeypatch):
    monkeypatch.setattr(
        "app.api.health.get_settings",
        lambda: Settings(llm_base_url="", llm_api_key="", llm_model="", mock_llm=True),
    )
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["mock_llm"] is True
    assert body["llm_configured"] is False


def test_configuration_defaults_are_safe(monkeypatch):
    for name in (
        "APP_NAME",
        "APP_VERSION",
        "ENVIRONMENT",
        "API_PREFIX",
        "FRONTEND_ORIGIN",
        "MOCK_LLM",
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "LLM_MODEL",
        "LLM_TIMEOUT_SECONDS",
        "LLM_MAX_ATTEMPTS",
        "LLM_MAX_RETRY_DELAY_SECONDS",
        "LLM_INPUT_COST_PER_MILLION_TOKENS",
        "LLM_OUTPUT_COST_PER_MILLION_TOKENS",
        "LLM_PRICING_VERSION",
        "LOG_LEVEL",
        "STORAGE_ROOT",
        "MAX_UPLOAD_SIZE_MB",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=None)
    assert settings.app_name == "Transmute API"
    assert settings.mock_llm is True
    assert settings.llm_api_key.get_secret_value() == ""
    assert settings.log_level == "INFO"
    assert settings.max_upload_size_mb == 10


def test_application_starts_and_exposes_openapi():
    with TestClient(app) as client:
        response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == app_settings.app_name

