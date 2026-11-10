from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app


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


def test_configuration_defaults_are_safe():
    settings = Settings(_env_file=None)
    assert settings.mock_llm is True
    assert settings.llm_api_key.get_secret_value() == ""
    assert settings.log_level == "INFO"
    assert settings.max_upload_size_mb == 10


def test_application_starts_and_exposes_openapi():
    with TestClient(app) as client:
        response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Transmute API"

