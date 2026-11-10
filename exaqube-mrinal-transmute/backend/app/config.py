"""Typed application settings with safe local defaults."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Transmute API"
    app_version: str = "0.1.0"
    environment: str = "development"
    api_prefix: str = "/api"
    frontend_origin: str = "http://localhost:3000"
    llm_base_url: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = ""
    mock_llm: bool = True
    log_level: str = "INFO"
    storage_root: Path = Path("./storage")
    max_upload_size_mb: int = Field(default=10, ge=1, le=10)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
            raise ValueError("LOG_LEVEL must be CRITICAL, ERROR, WARNING, INFO, or DEBUG.")
        return normalized

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key.get_secret_value() and self.llm_model)


@lru_cache
def get_settings() -> Settings:
    return Settings()

