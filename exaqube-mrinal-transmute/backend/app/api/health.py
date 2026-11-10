from fastapi import APIRouter

from app.config import get_settings
from app.storage.manager import storage_available

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, object]:
    settings = get_settings()
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "ok",
        "storage_available": storage_available(settings.storage_root),
        "mock_llm": settings.mock_llm,
        "llm_configured": settings.llm_configured,
    }

