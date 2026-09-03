import sys
from pathlib import Path

# Make pipeline directory importable
PIPELINE_DIR = str(Path(__file__).parent.parent)
if PIPELINE_DIR not in sys.path:
    sys.path.insert(0, PIPELINE_DIR)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from routes.runs import router as runs_router
from routes.reports import router as reports_router
from routes.hitl import router as hitl_router
from routes.events import router as events_router

app = FastAPI(title="Market Research Intelligence", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(runs_router, prefix="/api/v1")
app.include_router(reports_router, prefix="/api/v1")
app.include_router(hitl_router, prefix="/api/v1")
app.include_router(events_router, prefix="/api/v1")

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
