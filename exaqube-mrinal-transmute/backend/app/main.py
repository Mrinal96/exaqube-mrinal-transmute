"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import conversions, events, health, uploads, workflows
from app.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.storage.manager import storage_available

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    storage_available(settings.storage_root)
    logger.info("application_started")
    yield
    logger.info("application_stopped")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Foundation API for semantic document transformation workflows.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid4()))
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


register_error_handlers(app)
app.include_router(health.router)
app.include_router(uploads.router, prefix=settings.api_prefix)
app.include_router(conversions.router, prefix=settings.api_prefix)
app.include_router(workflows.router, prefix=settings.api_prefix)
app.include_router(events.router, prefix=settings.api_prefix)

