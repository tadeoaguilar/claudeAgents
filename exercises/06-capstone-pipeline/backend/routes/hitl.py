from fastapi import APIRouter, HTTPException

from state import registry

router = APIRouter()


@router.post("/runs/{run_id}/approve")
def approve_run(run_id: str):
    record = registry.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    if record.status != "awaiting_approval":
        raise HTTPException(status_code=409, detail=f"run is not awaiting approval (status: {record.status})")
    registry.resolve_hitl(run_id, approved=True)
    return {"run_id": run_id, "decision": "approved"}


@router.post("/runs/{run_id}/reject")
def reject_run(run_id: str):
    record = registry.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    if record.status != "awaiting_approval":
        raise HTTPException(status_code=409, detail=f"run is not awaiting approval (status: {record.status})")
    registry.resolve_hitl(run_id, approved=False)
    return {"run_id": run_id, "decision": "rejected"}
