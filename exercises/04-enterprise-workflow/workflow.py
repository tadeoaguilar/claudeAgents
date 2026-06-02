"""
Exercise 04 — Enterprise Workflow with HITL

Invoice processing agent with:
  - Human-in-the-loop approval gate
  - Append-only audit trail (audit_log.jsonl)
  - Exponential backoff retry
  - Structured error handling

Run:
    python workflow.py

When prompted, type:
    approve <request_id>
    reject  <request_id>
"""

import json
import os
import time
import uuid
import threading
from dataclasses import dataclass, asdict, field
from enum import Enum
from typing import Any

from dotenv import load_dotenv
import anthropic
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
console = Console()

AUDIT_LOG_PATH = "audit_log.jsonl"

# ──────────────────────────────────────────────
# 1. Audit logger
# ──────────────────────────────────────────────

def audit(event: str, data: dict) -> None:
    record = {
        "timestamp": time.time(),
        "event": event,
        **data
    }
    with open(AUDIT_LOG_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")
    console.print(f"  [dim][AUDIT] {event} | {json.dumps(data)[:120]}[/dim]")


# ──────────────────────────────────────────────
# 2. Mock data
# ──────────────────────────────────────────────

INVOICE_DB = {
    "INV-2025-0042": {
        "vendor": "Acme Cloud Services",
        "amount_usd": 8750.00,
        "currency": "USD",
        "due_date": "2025-07-15",
        "po_number": "PO-9981",
        "line_items": [
            {"description": "Cloud compute — June 2025", "amount": 6500.00},
            {"description": "Storage tier upgrade", "amount": 2250.00},
        ],
        "submitted_by": "finance@acme.com",
    },
    "INV-2025-0043": {
        "vendor": "UNKNOWN VENDOR LLC",
        "amount_usd": 250.00,
        "currency": "USD",
        "due_date": "2025-06-30",
        "po_number": None,
        "line_items": [{"description": "Consulting services", "amount": 250.00}],
        "submitted_by": "external@unknown.com",
    },
}

APPROVED_VENDORS = {"Acme Cloud Services", "TechParts Inc.", "Global IT Supplies"}
PURCHASE_ORDERS  = {"PO-9981", "PO-1234", "PO-5678"}


# ──────────────────────────────────────────────
# 3. HITL approval system
# ──────────────────────────────────────────────

class ApprovalStatus(Enum):
    PENDING  = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMEOUT  = "timeout"

@dataclass
class ApprovalRequest:
    id: str
    action: str
    details: dict
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: float = field(default_factory=time.time)
    resolved_at: float | None = None
    resolver: str | None = None
    reason: str | None = None

_approval_store: dict[str, ApprovalRequest] = {}
_approval_lock = threading.Lock()

def create_approval_request(action: str, details: dict) -> str:
    req = ApprovalRequest(
        id=str(uuid.uuid4())[:8],
        action=action,
        details=details,
    )
    with _approval_lock:
        _approval_store[req.id] = req

    audit("approval_requested", {"request_id": req.id, "action": action, "details": details})

    console.print(Panel(
        f"[bold yellow]APPROVAL REQUIRED[/bold yellow]\n\n"
        f"ID:     [bold]{req.id}[/bold]\n"
        f"Action: {action}\n"
        f"Details: {json.dumps(details, indent=2)}\n\n"
        f"Type [bold green]approve {req.id}[/bold green] or [bold red]reject {req.id}[/bold red]",
        border_style="yellow"
    ))

    return req.id

def poll_approval(request_id: str, timeout_seconds: float = 120.0) -> ApprovalStatus:
    start = time.time()
    while True:
        with _approval_lock:
            req = _approval_store.get(request_id)
            if req and req.status != ApprovalStatus.PENDING:
                return req.status

        if time.time() - start > timeout_seconds:
            with _approval_lock:
                if request_id in _approval_store:
                    _approval_store[request_id].status = ApprovalStatus.TIMEOUT
            audit("approval_timeout", {"request_id": request_id})
            return ApprovalStatus.TIMEOUT

        time.sleep(1.0)

def handle_approval_input():
    """Background thread: read approver input from stdin."""
    while True:
        try:
            line = input().strip()
        except EOFError:
            break
        parts = line.split()
        if len(parts) != 2:
            continue
        command, req_id = parts[0].lower(), parts[1]
        with _approval_lock:
            req = _approval_store.get(req_id)
            if not req:
                console.print(f"[red]Unknown request ID: {req_id}[/red]")
                continue
            if req.status != ApprovalStatus.PENDING:
                console.print(f"[yellow]Request {req_id} already resolved: {req.status.value}[/yellow]")
                continue
            if command == "approve":
                req.status = ApprovalStatus.APPROVED
                req.resolved_at = time.time()
                req.resolver = "human-approver"
                audit("approval_granted", {"request_id": req_id})
                console.print(f"[green]✓ Approved: {req_id}[/green]")
            elif command == "reject":
                req.status = ApprovalStatus.REJECTED
                req.resolved_at = time.time()
                req.resolver = "human-approver"
                audit("approval_rejected", {"request_id": req_id})
                console.print(f"[red]✗ Rejected: {req_id}[/red]")


# ──────────────────────────────────────────────
# 4. Tool implementations
# ──────────────────────────────────────────────

def get_invoice(invoice_id: str) -> str:
    invoice = INVOICE_DB.get(invoice_id)
    if not invoice:
        return json.dumps({"error": f"Invoice '{invoice_id}' not found"})
    audit("invoice_retrieved", {"invoice_id": invoice_id})
    return json.dumps(invoice)

def validate_invoice(invoice_id: str) -> str:
    invoice = INVOICE_DB.get(invoice_id)
    if not invoice:
        return json.dumps({"valid": False, "reason": "Invoice not found"})

    issues = []
    if invoice["vendor"] not in APPROVED_VENDORS:
        issues.append(f"Vendor '{invoice['vendor']}' is not on the approved vendor list")
    if invoice["po_number"] not in PURCHASE_ORDERS:
        issues.append(f"PO number '{invoice['po_number']}' does not exist or is invalid")
    if invoice["amount_usd"] > 10_000:
        issues.append(f"Amount ${invoice['amount_usd']:,.2f} exceeds auto-approval threshold of $10,000")

    result = {
        "valid": len(issues) == 0,
        "issues": issues,
        "vendor_approved": invoice["vendor"] in APPROVED_VENDORS,
        "po_valid": invoice["po_number"] in PURCHASE_ORDERS,
        "amount_usd": invoice["amount_usd"],
    }
    audit("invoice_validated", {"invoice_id": invoice_id, **result})
    return json.dumps(result)

def request_human_approval_tool(action: str, details_json: str) -> str:
    """Tool wrapper for the HITL gate."""
    try:
        details = json.loads(details_json)
    except json.JSONDecodeError:
        details = {"raw": details_json}

    request_id = create_approval_request(action, details)
    status = poll_approval(request_id, timeout_seconds=120.0)
    return json.dumps({"status": status.value, "request_id": request_id})

def authorise_payment(invoice_id: str, approval_request_id: str) -> str:
    req = _approval_store.get(approval_request_id)
    if not req or req.status != ApprovalStatus.APPROVED:
        return json.dumps({"success": False, "reason": "Payment not approved or approval expired"})

    audit("payment_authorised", {
        "invoice_id": invoice_id,
        "approval_request_id": approval_request_id,
        "amount_usd": INVOICE_DB.get(invoice_id, {}).get("amount_usd"),
    })
    return json.dumps({
        "success": True,
        "authorisation_code": f"AUTH-{str(uuid.uuid4())[:8].upper()}",
        "invoice_id": invoice_id,
    })


TOOL_REGISTRY = {
    "get_invoice":                get_invoice,
    "validate_invoice":           validate_invoice,
    "request_human_approval":     request_human_approval_tool,
    "authorise_payment":          authorise_payment,
}

TOOLS = [
    {
        "name": "get_invoice",
        "description": "Retrieve full invoice details by invoice ID.",
        "input_schema": {
            "type": "object",
            "properties": {"invoice_id": {"type": "string"}},
            "required": ["invoice_id"]
        }
    },
    {
        "name": "validate_invoice",
        "description": "Validate an invoice: check vendor approval, PO number, and amount threshold.",
        "input_schema": {
            "type": "object",
            "properties": {"invoice_id": {"type": "string"}},
            "required": ["invoice_id"]
        }
    },
    {
        "name": "request_human_approval",
        "description": (
            "Pause and request human approval before a sensitive action. "
            "Returns {\"status\": \"approved\" | \"rejected\" | \"timeout\", \"request_id\": str}. "
            "Do NOT proceed with payment unless status is 'approved'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Short description of the action requiring approval"
                },
                "details_json": {
                    "type": "string",
                    "description": "JSON string with relevant details for the approver"
                }
            },
            "required": ["action", "details_json"]
        }
    },
    {
        "name": "authorise_payment",
        "description": "Authorise payment for a validated and approved invoice.",
        "input_schema": {
            "type": "object",
            "properties": {
                "invoice_id": {"type": "string"},
                "approval_request_id": {
                    "type": "string",
                    "description": "The request_id returned by request_human_approval"
                }
            },
            "required": ["invoice_id", "approval_request_id"]
        }
    },
]


# ──────────────────────────────────────────────
# 5. System prompt
# ──────────────────────────────────────────────

SYSTEM_PROMPT = """You are an invoice processing agent for the finance team.

For each invoice you receive, follow this exact workflow:

STEP 1 — Retrieve the invoice using get_invoice
STEP 2 — Validate the invoice using validate_invoice
  - If validation fails: report the issues and STOP. Do not proceed to payment.
STEP 3 — Request human approval using request_human_approval
  - Action: "Authorise payment for invoice <ID>"
  - Details: include vendor, amount, and validation summary as JSON
  - If approval returns "rejected" or "timeout": report the outcome and STOP
STEP 4 — Authorise payment using authorise_payment (only if approved)
STEP 5 — Return a structured JSON summary:
{
  "invoice_id": string,
  "outcome": "authorised" | "rejected_validation" | "rejected_approval" | "approval_timeout",
  "summary": string (1-2 sentences),
  "authorisation_code": string | null
}

CRITICAL RULES:
- Never call authorise_payment without a successful approval
- Always include the approval_request_id when calling authorise_payment
- If any step fails, stop and report — do not guess or proceed
"""


# ──────────────────────────────────────────────
# 6. Agent loop with retry
# ──────────────────────────────────────────────

def run_invoice_agent(invoice_id: str) -> dict:
    console.print(Panel(
        f"[bold cyan]Processing invoice:[/bold cyan] {invoice_id}",
        title="Invoice Agent"
    ))
    audit("agent_started", {"invoice_id": invoice_id})

    messages = [{"role": "user", "content": f"Process invoice {invoice_id}."}]

    for iteration in range(1, 15):
        # Exponential backoff retry for API errors
        for attempt in range(3):
            try:
                response = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=1024,
                    system=[{
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"}
                    }],
                    tools=TOOLS,
                    messages=messages,
                )
                break
            except anthropic.APIError as e:
                if attempt == 2:
                    raise
                wait = 2 ** attempt
                console.print(f"  [red]API error (attempt {attempt+1}): {e}. Retrying in {wait}s…[/red]")
                time.sleep(wait)

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            raw = next(
                (block.text for block in response.content if hasattr(block, "text")),
                "{}"
            )
            try:
                result = json.loads(raw)
            except json.JSONDecodeError:
                result = {"outcome": "error", "raw": raw}

            audit("agent_completed", {"invoice_id": invoice_id, **result})
            console.print(Panel(
                json.dumps(result, indent=2),
                title=f"[bold]Invoice {invoice_id} Result[/bold]"
            ))
            return result

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    console.print(f"  [yellow]→ {block.name}[/yellow]({json.dumps(block.input)[:80]})")
                    fn = TOOL_REGISTRY.get(block.name)
                    result = fn(**block.input) if fn else json.dumps({"error": "tool not found"})
                    audit("tool_called", {"tool": block.name, "input": block.input, "output": result[:200]})
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
            messages.append({"role": "user", "content": tool_results})

    return {"outcome": "error", "reason": "max_iterations_reached"}


# ──────────────────────────────────────────────
# 7. Main
# ──────────────────────────────────────────────

if __name__ == "__main__":
    # Start the approval input listener in a background thread
    input_thread = threading.Thread(target=handle_approval_input, daemon=True)
    input_thread.start()

    console.print("[dim]Approval listener started. Type 'approve <id>' or 'reject <id>' when prompted.[/dim]\n")

    for invoice_id in ["INV-2025-0042", "INV-2025-0043"]:
        run_invoice_agent(invoice_id)
        console.print("\n" + "─" * 60 + "\n")
        time.sleep(1)
