"""Typed application settings with safe local defaults."""

from functools import lru_cache
from decimal import Decimal
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
    llm_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    llm_max_attempts: int = Field(default=3, ge=1, le=5)
    llm_max_retry_delay_seconds: float = Field(default=60.0, ge=0, le=60)
    llm_input_cost_per_million_tokens: Decimal | None = Field(default=None, ge=0)
    llm_output_cost_per_million_tokens: Decimal | None = Field(default=None, ge=0)
    llm_pricing_version: str | None = None
    mock_llm: bool = True
    log_level: str = "INFO"
    storage_root: Path = Path("./storage")
    max_upload_size_mb: int = Field(default=10, ge=1, le=10)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_ignore_empty=True,
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
        return bool(self.llm_base_url.strip() and self.llm_model.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()

