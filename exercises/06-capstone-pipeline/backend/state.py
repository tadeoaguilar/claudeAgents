import threading
import time
from dataclasses import dataclass, field
from typing import Literal, Optional

RunStatus = Literal["queued", "running", "awaiting_approval", "approved", "rejected", "delivered", "error"]


@dataclass
class RunRecord:
    run_id: str
    query: str
    status: RunStatus = "queued"
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    error: Optional[str] = None
    report: Optional[str] = None
    risk_score: Optional[float] = None
    hitl_request: Optional[dict] = None
    events: list = field(default_factory=list)
    _hitl_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _hitl_decision: Optional[bool] = field(default=None, repr=False)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "query": self.query,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "risk_score": self.risk_score,
            "hitl_request": self.hitl_request,
            "event_count": len(self.events),
        }


class RunRegistry:
    """Thread-safe in-memory store for all pipeline runs."""

    def __init__(self):
        self._lock = threading.Lock()
        self._runs: dict[str, RunRecord] = {}

    def create(self, run_id: str, query: str) -> RunRecord:
        record = RunRecord(run_id=run_id, query=query)
        with self._lock:
            self._runs[run_id] = record
        return record

    def get(self, run_id: str) -> Optional[RunRecord]:
        with self._lock:
            return self._runs.get(run_id)

    def list_all(self) -> list[RunRecord]:
        with self._lock:
            return sorted(self._runs.values(), key=lambda r: r.started_at, reverse=True)

    def update_status(self, run_id: str, status: RunStatus, **kwargs) -> None:
        with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                return
            record.status = status
            for k, v in kwargs.items():
                setattr(record, k, v)

    def append_event(self, run_id: str, event_type: str, data: dict) -> None:
        with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                return
            record.events.append({"type": event_type, "data": data})

    def register_hitl(self, run_id: str, request) -> threading.Event:
        """Register a pending HITL gate; returns the Event to wait on."""
        with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                raise KeyError(f"Unknown run_id: {run_id}")
            record.status = "awaiting_approval"
            record.hitl_request = {
                "run_id": request.run_id,
                "reason": request.reason,
                "risk_score": request.risk_score,
                "risk_level": request.risk_level,
                "summary_headline": request.summary_headline,
            }
            record.events.append({
                "type": "hitl_required",
                "data": {
                    "risk_score": request.risk_score,
                    "risk_level": request.risk_level,
                    "headline": request.summary_headline,
                    "reason": request.reason,
                },
            })
            event = record._hitl_event
        return event

    def get_hitl_decision(self, run_id: str) -> bool:
        with self._lock:
            record = self._runs.get(run_id)
            return bool(record and record._hitl_decision)

    def resolve_hitl(self, run_id: str, approved: bool) -> bool:
        """Called by approve/reject endpoints to unblock the pipeline thread."""
        with self._lock:
            record = self._runs.get(run_id)
            if record is None or record.status != "awaiting_approval":
                return False
            record._hitl_decision = approved
            record.status = "approved" if approved else "rejected"
            record._hitl_event.set()
        return True


registry = RunRegistry()
