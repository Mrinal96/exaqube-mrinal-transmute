"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
import re
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import conversions, events, health, interpretations, plans, transformations, uploads, workflows
from app.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging, log_context
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


REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


@app.middleware("http")
async def request_context(request: Request, call_next):
    incoming = request.headers.get("x-request-id", "")
    request_id = incoming if REQUEST_ID_PATTERN.fullmatch(incoming) else str(uuid4())
    request.state.request_id = request_id
    api_prefix = settings.api_prefix.rstrip("/")
    path = request.url.path
    path_parts = path[len(api_prefix):].strip("/").split("/") if path.startswith(f"{api_prefix}/") else []
    operation = None
    document_id = None
    run_id = None
    if request.method == "POST" and len(path_parts) >= 3 and path_parts[0] == "documents":
        if path_parts[-1] == "interpretations":
            operation = "interpretation"
        elif path_parts[-1] == "plans":
            operation = "planning"
        elif path_parts[-1] == "transformations":
            operation = "transformation"
        if operation:
            document_id = path_parts[1]
            run_id = str(uuid4())
    request.state.run_id = run_id
    with log_context(request_id=request_id, run_id=run_id, document_id=document_id, operation=operation):
        response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


register_error_handlers(app)
app.include_router(health.router)
app.include_router(uploads.router, prefix=settings.api_prefix)
app.include_router(interpretations.router, prefix=settings.api_prefix)
app.include_router(plans.router, prefix=settings.api_prefix)
app.include_router(transformations.router, prefix=settings.api_prefix)
app.include_router(conversions.router, prefix=settings.api_prefix)
app.include_router(workflows.router, prefix=settings.api_prefix)
app.include_router(events.router, prefix=settings.api_prefix)

