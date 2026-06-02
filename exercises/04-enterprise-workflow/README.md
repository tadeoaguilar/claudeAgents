# Exercise 04 — Enterprise Workflow with HITL

## Goal

Build a production-grade agent with Human-in-the-Loop gates, retry logic, and a full audit trail. By the end of this exercise you will:

- Implement an approval request/poll cycle
- Enforce HITL gates declaratively via the system prompt
- Build an append-only audit log
- Add exponential backoff retry for API errors

## Time Estimate

~90 minutes

## The Task

Build an **invoice processing agent** that:

1. Reads invoice data
2. Validates the invoice (check vendor, amount, approvals)
3. **Pauses for human approval** before marking payment as authorised
4. Records every action to an audit log
5. Handles failures gracefully

This mimics a real finance automation workflow where an LLM can handle routine work but a human must approve the final payment action.

---

## The HITL Pattern in This Exercise

The agent has a `request_human_approval` tool. When it calls this tool:

1. Your code creates an approval record and "notifies" the approver (simulated here by printing to the console)
2. The agent waits (polls the approval store)
3. You type `approve <id>` or `reject <id>` in the terminal to simulate the approver's action
4. The agent continues or aborts based on the decision

In production, the notification would be a Slack message, email, or approval UI with deep links.

---

## Instructions

1. Run: `python workflow.py`
2. When the agent pauses for approval, type `approve <request_id>` in the terminal
3. Observe the audit log written to `audit_log.jsonl`
4. Try rejecting an approval and observe how the agent handles it
5. Complete the challenges

---

## Challenges

### Challenge A — Conditional HITL
Modify the system prompt and the validation logic so that invoices under $500 are auto-approved (no HITL), but invoices over $500 always require human approval. Add a `get_approval_threshold(vendor: str) -> float` tool that returns the vendor-specific threshold.

### Challenge B — Audit log analysis
After running several invoices, write a Python script that reads `audit_log.jsonl` and prints:
- Total invoices processed
- Approval rate (approved vs. rejected vs. timeout)
- Average time from request to approval decision
- Invoices that failed validation

### Challenge C — Timeout handling
Set the approval timeout to 10 seconds. When it expires, the agent should move the invoice to a "pending manual review" queue (a JSON file) instead of failing. Add a `review_queue.py` script that reads and displays the pending queue.

---

## Key Concepts Practiced

- HITL gate implementation
- Audit trail with structured JSONL
- Exponential backoff for API errors
- Graceful failure handling

---

## Next

→ [Exercise 05 — Observability](../05-observability/README.md)
