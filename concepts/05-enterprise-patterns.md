# Concept 05 — Enterprise Patterns: HITL, Approval Workflows, and Multi-Tenancy

## The Enterprise Problem: Trust and Control

Deploying autonomous agents in an enterprise is fundamentally a governance problem. The business must answer:

- Which actions can the agent take without human review?
- Who approves sensitive actions, and how quickly?
- How do we prove to auditors that the agent behaved correctly?
- How do we isolate one tenant's data from another's?
- What happens when an agent is wrong or misbehaves?

This concept covers the architectural patterns that answer these questions.

---

## Human-in-the-Loop (HITL)

### What It Is

HITL is a gate in the agent loop where execution pauses and a human must take an action before the agent continues. It is not about distrusting the agent — it is about matching the level of oversight to the stakes of the action.

### The HITL Decision Matrix

Not every action needs a human. Use this matrix to decide:

```
                        REVERSIBLE        IRREVERSIBLE
                    ┌──────────────┬──────────────────────┐
HIGH CONFIDENCE     │  Auto-approve│  HITL (confirm gate) │
                    ├──────────────┼──────────────────────┤
LOW CONFIDENCE      │  HITL (soft) │  HITL (hard block)   │
                    └──────────────┴──────────────────────┘
```

- **Auto-approve**: Read a database, generate a draft, summarise a document
- **HITL soft gate**: Send a low-priority email, create a Jira ticket, write to a staging database
- **HITL confirm gate**: Delete a record, update a production config, charge a customer
- **HITL hard block**: Execute a financial transaction above threshold, publish to external channels, modify access controls

### Implementing a HITL Gate

```python
import time
import uuid
from enum import Enum

class ApprovalStatus(Enum):
    PENDING  = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMEOUT  = "timeout"

class ApprovalRequest:
    def __init__(self, action: str, details: dict, approver_email: str, timeout_seconds: int = 3600):
        self.id = str(uuid.uuid4())
        self.action = action
        self.details = details
        self.approver_email = approver_email
        self.timeout_seconds = timeout_seconds
        self.status = ApprovalStatus.PENDING
        self.created_at = time.time()
        self.resolved_at: float | None = None
        self.resolver: str | None = None
        self.reason: str | None = None

# Approval store (in production: database table)
_approval_store: dict[str, ApprovalRequest] = {}

def request_approval(action: str, details: dict, approver_email: str) -> str:
    """Create an approval request, notify the approver, return the request ID."""
    req = ApprovalRequest(action, details, approver_email)
    _approval_store[req.id] = req

    # In production: send an email/Slack notification with approve/reject links
    notify_approver(req)

    return req.id

def poll_approval(request_id: str, poll_interval: float = 5.0) -> ApprovalStatus:
    """Block until the request is resolved or times out."""
    req = _approval_store[request_id]

    while True:
        if req.status != ApprovalStatus.PENDING:
            return req.status

        if time.time() - req.created_at > req.timeout_seconds:
            req.status = ApprovalStatus.TIMEOUT
            return req.status

        time.sleep(poll_interval)

def approve(request_id: str, resolver: str, reason: str = "") -> None:
    req = _approval_store[request_id]
    req.status = ApprovalStatus.APPROVED
    req.resolved_at = time.time()
    req.resolver = resolver
    req.reason = reason

def reject(request_id: str, resolver: str, reason: str = "") -> None:
    req = _approval_store[request_id]
    req.status = ApprovalStatus.REJECTED
    req.resolved_at = time.time()
    req.resolver = resolver
    req.reason = reason
```

The agent calls this as a tool:

```python
def request_human_approval(action_description: str, action_details: dict) -> str:
    """
    HITL gate: pause and request human approval before a sensitive action.
    Returns 'approved', 'rejected', or 'timeout'.
    """
    request_id = request_approval(
        action=action_description,
        details=action_details,
        approver_email="ops-team@company.com"
    )
    status = poll_approval(request_id)
    return status.value
```

In the system prompt, tell the agent when to use this gate:

```
Before taking any of the following actions, you MUST call request_human_approval
and wait for 'approved' before proceeding:
- Sending any external email or communication
- Modifying any record in the production database
- Creating or deleting any cloud infrastructure
- Any action that costs more than $1,000

If request_human_approval returns 'rejected' or 'timeout', stop and report why you could not complete the task.
```

---

## Audit Trail

Every enterprise agent must maintain a tamper-evident audit trail. This is both a compliance requirement and a debugging tool.

### What to Log

Log at the **turn level** (every model call) and the **tool level** (every function execution):

```python
import json
import time
import uuid
from dataclasses import dataclass, field, asdict

@dataclass
class ToolCallLog:
    tool_name: str
    input: dict
    output: str
    duration_ms: float
    timestamp: float = field(default_factory=time.time)
    error: str | None = None

@dataclass
class AgentTurnLog:
    run_id: str
    turn_number: int
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    stop_reason: str
    tool_calls: list[ToolCallLog]
    duration_ms: float
    timestamp: float = field(default_factory=time.time)
    tenant_id: str | None = None
    user_id: str | None = None

def log_turn(log: AgentTurnLog, store) -> None:
    """Persist to append-only store (database, S3, CloudWatch, etc.)"""
    store.append(asdict(log))
```

### Audit Trail Requirements by Compliance Framework

| Framework | Minimum Retention | Required Fields | Immutability |
|---|---|---|---|
| SOC 2 | 1 year | Action, actor, timestamp, outcome | Required |
| GDPR | 30 days (can delete on request) | User ID, data accessed | Required for PII access |
| HIPAA | 6 years | All PHI access, all decisions | Required |
| PCI DSS | 1 year | All access to cardholder data | Required |
| ISO 27001 | Defined by risk assessment | Security events | Recommended |

---

## Multi-Tenancy

When your agent serves multiple customers or business units, you must ensure strict data isolation.

### Tenant Isolation Pattern

Never let tenant A's data reach tenant B. Enforce this at the tool layer, not the prompt layer:

```python
class TenantScopedDatabaseTool:
    """
    Wraps database access to enforce tenant isolation.
    The agent cannot bypass this — it never sees the filtering logic.
    """

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id

    def query_database(self, sql: str) -> str:
        # Validate the SQL is a SELECT
        if not sql.strip().upper().startswith("SELECT"):
            raise PermissionError("Only SELECT statements are allowed")

        # Automatically inject tenant filter
        # In production, use a proper SQL parser rather than string manipulation
        scoped_sql = self._inject_tenant_filter(sql)

        return execute_query(scoped_sql)

    def _inject_tenant_filter(self, sql: str) -> str:
        # Simplification: in production, use sqlglot or similar
        return f"SELECT * FROM ({sql}) AS scoped WHERE tenant_id = '{self.tenant_id}'"
```

Create a fresh, tenant-scoped tool instance per request:

```python
def handle_request(tenant_id: str, user_id: str, goal: str) -> str:
    db_tool = TenantScopedDatabaseTool(tenant_id)

    return run_agent(
        user_goal=goal,
        tool_implementations={
            "query_database": db_tool.query_database
        },
        context={"tenant_id": tenant_id, "user_id": user_id}
    )
```

### System Prompt Parameterisation

Never share a single static system prompt across tenants. Inject tenant-specific context:

```python
def build_system_prompt(tenant_config: dict) -> str:
    return f"""You are a data analyst assistant for {tenant_config['company_name']}.

You have access to the following databases:
{json.dumps(tenant_config['allowed_databases'], indent=2)}

Data classification for this tenant: {tenant_config['data_classification']}

Compliance requirements: {', '.join(tenant_config['compliance_frameworks'])}

{tenant_config.get('custom_instructions', '')}
"""
```

---

## Rate Limiting and Cost Control per Tenant

Prevent any single tenant from consuming disproportionate resources:

```python
from collections import defaultdict
import threading

class TenantRateLimiter:
    def __init__(self):
        self._lock = threading.Lock()
        self._token_usage: dict[str, int] = defaultdict(int)
        self._run_counts: dict[str, int] = defaultdict(int)

    def check_and_consume(
        self,
        tenant_id: str,
        estimated_tokens: int,
        token_limit_per_hour: int,
        run_limit_per_hour: int
    ) -> None:
        with self._lock:
            if self._token_usage[tenant_id] + estimated_tokens > token_limit_per_hour:
                raise QuotaExceededError(f"Tenant {tenant_id} exceeded hourly token quota")
            if self._run_counts[tenant_id] >= run_limit_per_hour:
                raise QuotaExceededError(f"Tenant {tenant_id} exceeded hourly run quota")

            self._token_usage[tenant_id] += estimated_tokens
            self._run_counts[tenant_id] += 1

rate_limiter = TenantRateLimiter()
```

---

## Guardrails and Content Policy Enforcement

For regulated industries, the system prompt alone is insufficient. Add deterministic guardrails at the tool execution layer:

```python
import re

PII_PATTERNS = [
    r'\b\d{3}-\d{2}-\d{4}\b',          # SSN
    r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b',  # Credit card
    r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',  # Email
]

def check_pii_in_output(text: str) -> list[str]:
    """Return list of PII pattern names found in text."""
    found = []
    for pattern in PII_PATTERNS:
        if re.search(pattern, text):
            found.append(pattern)
    return found

def safe_tool_wrapper(fn: callable) -> callable:
    """Wrap any tool to check its output for PII before returning to the agent."""
    def wrapper(*args, **kwargs):
        result = fn(*args, **kwargs)
        pii_found = check_pii_in_output(str(result))
        if pii_found:
            # Mask or redact; log the incident
            log_pii_detection(fn.__name__, pii_found)
            result = redact_pii(str(result))
        return result
    return wrapper
```

---

## Rollback and Recovery

Agents that take state-modifying actions must support rollback.

```python
class ActionLog:
    """Records reversible actions so they can be undone."""

    def __init__(self):
        self.actions: list[dict] = []

    def record(self, action_type: str, payload: dict, rollback_fn: callable) -> None:
        self.actions.append({
            "id": str(uuid.uuid4()),
            "type": action_type,
            "payload": payload,
            "rollback_fn": rollback_fn,
            "timestamp": time.time(),
        })

    def rollback_all(self) -> None:
        """Undo all recorded actions in reverse order."""
        for action in reversed(self.actions):
            try:
                action["rollback_fn"](action["payload"])
            except Exception as e:
                log_rollback_failure(action, e)
```

---

## Next

→ [Concept 06 — Deployment Lifecycle](./06-deployment-lifecycle.md)
