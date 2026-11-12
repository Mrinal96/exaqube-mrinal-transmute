"""Process-local shared service instances used by FastAPI dependency injection."""

from functools import lru_cache

from app.config import get_settings
from app.services.interpretation import InterpretationService
from app.services.llm import LLMService
from app.services.planning import PlanningService


@lru_cache
def get_llm_service() -> LLMService:
    return LLMService(get_settings())


@lru_cache
def get_interpretation_service() -> InterpretationService:
    settings = get_settings()
    return InterpretationService(get_llm_service(), settings.storage_root)


@lru_cache
def get_planning_service() -> PlanningService:
    settings = get_settings()
    return PlanningService(get_llm_service(), settings.storage_root)
