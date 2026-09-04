import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from state import registry

router = APIRouter()

TERMINAL_STATUSES = {"delivered", "rejected", "error"}


@router.get("/runs/{run_id}/events")
async def stream_events(run_id: str, request: Request):
    record = registry.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")

    async def event_generator():
        last_index = 0
        while True:
            if await request.is_disconnected():
                break

            run = registry.get(run_id)
            if run is None:
                yield {"event": "error", "data": json.dumps({"error": "run not found"})}
                break

            new_events = run.events[last_index:]
            for i, evt in enumerate(new_events):
                yield {
                    "id": str(last_index + i),
                    "event": evt["type"],
                    "data": json.dumps(evt["data"]),
                }
            last_index += len(new_events)

            # Heartbeat keeps Azure Container Apps ingress idle timer from firing
            if not new_events:
                yield {"event": "heartbeat", "data": "{}"}

            if run.status in TERMINAL_STATUSES and last_index >= len(run.events):
                yield {
                    "event": "terminal",
                    "data": json.dumps({"status": run.status}),
                }
                break

            await asyncio.sleep(0.5)

    return EventSourceResponse(event_generator())
