"""Server-sent workflow run events backed by persisted event snapshots."""

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.config import Settings, get_settings
from app.core.errors import APIError
from app.storage.workflows import WorkflowStore


router = APIRouter(prefix="/events", tags=["events"])


@router.get("/workflows/{workflow_id}/runs/{run_id}")
async def workflow_run_events(
    workflow_id: str,
    run_id: str,
    request: Request,
    after: int = 0,
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    store = WorkflowStore(settings.storage_root)
    try:
        run = await run_in_threadpool(store.get_run, workflow_id, run_id)
    except ValueError as exc:
        raise APIError(400, "invalid_workflow_run_id", "The workflow or run ID is invalid.") from exc
    if run is None:
        raise APIError(404, "workflow_run_not_found", "No workflow run matches these IDs.")
    try:
        cursor = max(after, int(request.headers.get("last-event-id", "0") or 0))
    except ValueError:
        cursor = max(after, 0)

    async def stream():
        nonlocal cursor
        while not await request.is_disconnected():
            current = await run_in_threadpool(store.get_run, workflow_id, run_id)
            if current is None:
                return
            for event in current.events:
                if event.sequence <= cursor:
                    continue
                payload = json.dumps(event.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
                yield f"id: {event.sequence}\nevent: {event.event}\ndata: {payload}\n\n"
                cursor = event.sequence
            if current.status in {"done", "failed", "cancelled"} and cursor >= len(current.events):
                yield "event: end\ndata: {}\n\n"
                return
            await asyncio.sleep(0.4)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
