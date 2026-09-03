from pathlib import Path

from fastapi import APIRouter, HTTPException

from state import registry

PIPELINE_DIR = str(Path(__file__).parent.parent.parent)
router = APIRouter()


@router.get("/runs/{run_id}/report")
def get_report(run_id: str):
    record = registry.get(run_id)
    if record and record.report:
        return {"run_id": run_id, "report_markdown": record.report}

    # Fall back to disk for historical runs
    report_path = Path(PIPELINE_DIR) / f"report_{run_id}.md"
    if report_path.exists():
        return {"run_id": run_id, "report_markdown": report_path.read_text()}

    raise HTTPException(status_code=404, detail="report not found")
