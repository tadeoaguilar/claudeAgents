# hitl.py
from dataclasses import dataclass
from typing import Optional

from observability import write_log_event

# ── Approval request ──────────────────────────────────────────────

@dataclass
class ApprovalRequest:
    run_id:           str
    reason:           str
    risk_score:       float
    risk_level:       str
    summary_headline: str

# ── Gate ─────────────────────────────────────────────────────────

def hitl_gate(request: ApprovalRequest, event_registry=None) -> bool:
    """
    Block until an operator approves or rejects the report.

    When event_registry is None (CLI mode): uses stdin input() loop.
    When event_registry is provided (web mode): blocks on threading.Event
    set by the web API approve/reject endpoints.

    Returns True  → approved, pipeline continues.
    Returns False → rejected, pipeline halts.
    """
    write_log_event("hitl_triggered", {
        "run_id":     request.run_id,
        "risk_score": request.risk_score,
        "risk_level": request.risk_level,
        "reason":     request.reason,
    })

    if event_registry is not None:
        return _web_gate(request, event_registry)

    _print_gate(request)

    while True:
        answer = input("  Approve report delivery? [y/n]: ").strip().lower()
        if answer in ("y", "yes"):
            write_log_event("hitl_decision", {
                "run_id":   request.run_id,
                "decision": "approved",
            })
            print("  Approved. Delivering report...\n")
            return True

        if answer in ("n", "no"):
            write_log_event("hitl_decision", {
                "run_id":   request.run_id,
                "decision": "rejected",
            })
            print("  Rejected. Pipeline halted.\n")
            return False

        print("  Please enter 'y' or 'n'.")


def _web_gate(request: ApprovalRequest, event_registry) -> bool:
    """Web mode: register the HITL request and block on threading.Event."""
    event = event_registry.register_hitl(request.run_id, request)
    timed_out = not event.wait(timeout=3600)

    if timed_out:
        write_log_event("hitl_decision", {
            "run_id":   request.run_id,
            "decision": "timeout",
        })
        return False

    approved = event_registry.get_hitl_decision(request.run_id)
    write_log_event("hitl_decision", {
        "run_id":   request.run_id,
        "decision": "approved" if approved else "rejected",
    })
    return approved


def _print_gate(request: ApprovalRequest) -> None:
    line = "=" * 62
    print(f"\n{line}")
    print("  ⚠️  HUMAN APPROVAL REQUIRED")
    print(line)
    print(f"  Run ID     : {request.run_id}")
    print(f"  Headline   : {request.summary_headline}")
    print(f"  Risk Score : {request.risk_score:.2f}  ({request.risk_level})")
    print(f"  Reason     : {request.reason}")
    print(line)