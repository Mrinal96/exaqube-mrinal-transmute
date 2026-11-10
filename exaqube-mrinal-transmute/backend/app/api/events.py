"""SSE namespace reserved for streaming workflow execution events."""

from fastapi import APIRouter

router = APIRouter(prefix="/events", tags=["events"])

