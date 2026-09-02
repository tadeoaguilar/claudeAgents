# hitl.py
from dataclasses import dataclass

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

def hitl_gate(request: ApprovalRequest) -> bool:
    """
    Block until an operator approves or rejects the report.

    Returns True  → approved, pipeline continues.
    Returns False → rejected, pipeline halts.
    """
    write_log_event("hitl_triggered", {
        "run_id":     request.run_id,
        "risk_score": request.risk_score,
        "risk_level": request.risk_level,
        "reason":     request.reason,
    })

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