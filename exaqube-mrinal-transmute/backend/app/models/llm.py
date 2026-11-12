"""Typed contracts shared by LLM providers and their callers."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LLMErrorCategory(StrEnum):
    CONFIGURATION = "configuration_error"
    TIMEOUT = "timeout"
    CONNECTION = "connection_error"
    PROVIDER = "provider_error"
    INVALID_RESPONSE = "invalid_response"


class LLMRequestMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["system", "user", "assistant"]
    content: str


class LLMTokenUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class LLMCompletionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str
    model: str
    provider: str
    usage: LLMTokenUsage | None = None
    finish_reason: str | None = None
    is_mock: bool = False
