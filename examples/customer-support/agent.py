"""
Example: Customer Support Agent

A production-close reference implementation of a support triage and resolution agent.

Features:
  - Classifies issue severity (P1-P4)
  - Looks up customer account and ticket history
  - Drafts a response
  - Escalates P1/P2 issues (simulated)
  - Full audit trail

This is a complete, runnable example — not a teaching exercise.

Run:
    python agent.py
"""

import json
import os
import time
import uuid
from dataclasses import dataclass
from enum import Enum

from dotenv import load_dotenv
import anthropic
from rich.console import Console
from rich.panel import Panel

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
console = Console()

# ── Mock data ──────────────────────────────────────────────────

CUSTOMER_DB = {
    "C-1001": {
        "name": "GlobalCorp Ltd",
        "plan": "Enterprise",
        "mrr_usd": 4500,
        "account_manager": "alice@support.io",
        "health_score": 62,  # <70 = at-risk
        "open_tickets": 2,
    }
}

KNOWLEDGE_BASE = {
    "login_failure": (
        "Common causes: (1) Expired password — reset at /settings/security. "
        "(2) MFA device lost — contact admin to disable. "
        "(3) IP allowlist blocking — check /settings/security/ip-allowlist."
    ),
    "data_export_crash": (
        "Known issue with exports >1,000 rows on versions <2.4.1. "
        "Workaround: export in batches of 500. Fix ships in v2.4.2 (ETA: 2025-06-15)."
    ),
}

# ── Tool implementations ────────────────────────────────────────

def lookup_customer(customer_id: str) -> str:
    data = CUSTOMER_DB.get(customer_id)
    if not data:
        return json.dumps({"error": f"Customer '{customer_id}' not found"})
    return json.dumps(data)

def search_knowledge_base(query: str) -> str:
    query_lower = query.lower()
    for key, content in KNOWLEDGE_BASE.items():
        if any(kw in query_lower for kw in key.split("_")):
            return json.dumps({"found": True, "key": key, "content": content})
    return json.dumps({"found": False, "message": "No matching KB article found"})

def get_ticket_history(customer_id: str) -> str:
    tickets = [
        {"id": "T-4421", "subject": "Export crash on large datasets", "status": "open", "age_days": 62},
        {"id": "T-4198", "subject": "Slow dashboard load", "status": "resolved", "age_days": 90},
    ]
    return json.dumps({"customer_id": customer_id, "tickets": tickets})

def escalate_to_account_manager(customer_id: str, reason: str, priority: str) -> str:
    customer = CUSTOMER_DB.get(customer_id, {})
    am = customer.get("account_manager", "support@support.io")
    console.print(f"  [red bold]ESCALATION[/red bold] → {am} | {priority} | {reason}")
    return json.dumps({
        "escalated": True,
        "notified": am,
        "escalation_id": f"ESC-{str(uuid.uuid4())[:6].upper()}",
    })

TOOL_REGISTRY = {
    "lookup_customer":          lookup_customer,
    "search_knowledge_base":    search_knowledge_base,
    "get_ticket_history":       get_ticket_history,
    "escalate_to_account_manager": escalate_to_account_manager,
}

TOOLS = [
    {
        "name": "lookup_customer",
        "description": "Retrieve account details for a customer: plan, MRR, health score, open tickets.",
        "input_schema": {"type": "object", "properties": {"customer_id": {"type": "string"}}, "required": ["customer_id"]}
    },
    {
        "name": "search_knowledge_base",
        "description": "Search the internal KB for solutions to common issues.",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
    },
    {
        "name": "get_ticket_history",
        "description": "Get open and recent tickets for a customer.",
        "input_schema": {"type": "object", "properties": {"customer_id": {"type": "string"}}, "required": ["customer_id"]}
    },
    {
        "name": "escalate_to_account_manager",
        "description": "Escalate an issue to the account manager. Use for P1/P2 issues or at-risk accounts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
                "reason": {"type": "string", "description": "Why escalation is needed"},
                "priority": {"type": "string", "enum": ["P1", "P2"]}
            },
            "required": ["customer_id", "reason", "priority"]
        }
    },
]

SYSTEM_PROMPT = """You are a senior customer support agent for a B2B SaaS company.

When you receive a support request:

1. Look up the customer account (lookup_customer) and ticket history (get_ticket_history)
2. Search the knowledge base for solutions (search_knowledge_base)
3. Assess severity:
   - P1: System completely down or data loss for Enterprise customers with health score <70
   - P2: Major feature broken, active business impact
   - P3: Non-critical issue, workaround available
   - P4: Minor issue / feature request

4. For P1 or P2: escalate_to_account_manager BEFORE drafting the response
5. Draft a response

Return ONLY this JSON:
{
  "priority": "P1" | "P2" | "P3" | "P4",
  "escalated": boolean,
  "root_cause": string,
  "response_to_customer": string (professional, empathetic, actionable),
  "internal_notes": string (for the support team — include relevant account context),
  "resolution_eta_hours": int | null
}
"""

def handle_support_ticket(customer_id: str, subject: str, body: str) -> dict:
    ticket_id = f"T-{str(uuid.uuid4())[:4].upper()}"
    console.print(Panel(
        f"[bold]Ticket:[/bold] {ticket_id}\n"
        f"[bold]Customer:[/bold] {customer_id}\n"
        f"[bold]Subject:[/bold] {subject}\n\n{body}",
        title="[cyan]Support Ticket[/cyan]"
    ))

    messages = [{
        "role": "user",
        "content": f"Customer ID: {customer_id}\nSubject: {subject}\n\n{body}"
    }]

    for _ in range(10):
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            tools=TOOLS,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            raw = next((b.text for b in response.content if hasattr(b, "text")), "{}")
            try:
                result = json.loads(raw)
            except json.JSONDecodeError:
                result = {"error": "parse_failed", "raw": raw}

            priority = result.get("priority", "?")
            color = {"P1": "red", "P2": "yellow", "P3": "blue", "P4": "dim"}.get(priority, "white")
            console.print(Panel(
                f"[{color}][bold]{priority}[/bold][/{color}] | Escalated: {result.get('escalated', '?')}\n\n"
                f"[bold]Response to customer:[/bold]\n{result.get('response_to_customer', '')}\n\n"
                f"[bold dim]Internal notes:[/bold dim] {result.get('internal_notes', '')}",
                title=f"[green]Ticket {ticket_id} Resolved[/green]"
            ))
            return result

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    console.print(f"  [yellow]→[/yellow] {block.name}({json.dumps(block.input)[:60]})")
                    fn = TOOL_REGISTRY.get(block.name)
                    result = fn(**block.input) if fn else json.dumps({"error": "not found"})
                    tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result})
            messages.append({"role": "user", "content": tool_results})

    return {"error": "max_iterations_reached"}


if __name__ == "__main__":
    handle_support_ticket(
        customer_id="C-1001",
        subject="Dashboard export crashes — urgent",
        body=(
            "Our finance team has been unable to export data for 2 months. "
            "Every time we try to export more than 1,000 rows, the page crashes. "
            "This is blocking our month-end reporting. We're an Enterprise customer "
            "and this is severely impacting our operations. Need this fixed ASAP."
        )
    )
