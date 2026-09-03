import asyncio
import json
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from state import registry
from runner import launch_pipeline

PIPELINE_DIR = str(Path(__file__).parent.parent.parent)
LOG_FILE = Path(PIPELINE_DIR) / "pipeline_runs.jsonl"

router = APIRouter()


class StartRunRequest(BaseModel):
    query: str


@router.post("/runs", status_code=202)
async def start_run(body: StartRunRequest, background_tasks: BackgroundTasks):
    if not body.query.strip():
        raise HTTPException(status_code=422, detail="query must not be empty")
    run_id = uuid.uuid4().hex[:12]
    registry.create(run_id, body.query.strip())
    background_tasks.add_task(launch_pipeline, run_id, body.query.strip())
    return {"run_id": run_id, "status": "queued"}


@router.get("/runs")
def list_runs():
    live = {r.run_id: r.to_dict() for r in registry.list_all()}

    # Hydrate historical runs from JSONL that are not already in memory
    if LOG_FILE.exists():
        pipeline_ends: dict[str, dict] = {}
        pipeline_starts: dict[str, dict] = {}
        try:
            for line in LOG_FILE.read_text().splitlines():
                if not line.strip():
                    continue
                evt = json.loads(line)
                rid = evt.get("run_id")
                if not rid:
                    continue
                if evt.get("event_type") == "pipeline_end":
                    pipeline_ends[rid] = evt
                elif evt.get("event_type") == "pipeline_start":
                    pipeline_starts[rid] = evt
        except Exception:
            pass

        for rid, end_evt in pipeline_ends.items():
            if rid not in live:
                live[rid] = {
                    "run_id": rid,
                    "query": pipeline_starts.get(rid, {}).get("query", ""),
                    "status": end_evt.get("status", "delivered"),
                    "started_at": pipeline_starts.get(rid, {}).get("timestamp"),
                    "finished_at": end_evt.get("timestamp"),
                    "risk_score": end_evt.get("risk_score"),
                    "hitl_request": None,
                    "error": None,
                    "event_count": 0,
                }

    return sorted(live.values(), key=lambda r: r.get("started_at") or 0, reverse=True)


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    record = registry.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    return record.to_dict()
