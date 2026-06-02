# Exercise 02 — Tool-Use Agent

## Goal

Build an agent with a realistic set of enterprise tools. By the end of this exercise you will:

- Define multiple tools with different return types
- Understand how Claude chooses which tool to call
- Handle parallel tool calls (Claude can request multiple tools in one turn)
- Implement a structured output schema

## Time Estimate

~45 minutes

## The Task

Build a **company research agent** that answers questions about companies by using three tools:

| Tool | What it does |
|---|---|
| `search_company_database` | Returns basic info: name, industry, founded, HQ |
| `get_financial_metrics` | Returns revenue, growth rate, employee count |
| `get_recent_news` | Returns last 3 news headlines with dates |

The agent must synthesise data from all three tools and return a structured JSON report.

---

## Key Concept: Parallel Tool Calls

Claude often calls multiple tools in a single turn when it determines they are independent:

```python
# Claude's response.content might contain TWO tool_use blocks in one turn:
[
  ToolUseBlock(name="search_company_database", input={"company": "Stripe"}),
  ToolUseBlock(name="get_financial_metrics",  input={"company": "Stripe"}),
]
```

Your code must handle this correctly — collect **all** results before sending them back.

In production, execute parallel tool calls concurrently using `asyncio` or `ThreadPoolExecutor`.

---

## Instructions

1. Read `agent.py` — pay attention to the `MOCK_DATABASE` and how each tool queries it
2. Run: `python agent.py`
3. Observe which tools Claude calls, and in which order
4. Complete the challenges

---

## Challenges

### Challenge A — Add a fourth tool
Add a `get_competitor_list(company: str) -> list[str]` tool. Update the system prompt to instruct the agent to include competitor data in its report. Observe how Claude decides when to call it.

### Challenge B — Parallel execution
The three tools are currently called synchronously in the mock. Wrap `execute_tool` in a `ThreadPoolExecutor` to run parallel tool calls concurrently. Measure the latency difference.

### Challenge C — Schema validation
The agent is instructed to return JSON. Add a `validate_output(json_str: str) -> bool` function that checks the output matches a defined schema (use `jsonschema` or a manual check). If validation fails, send the schema error back to the agent and ask it to fix the output.

---

## Key Concepts Practiced

- Multiple tool definitions with distinct schemas
- Handling parallel tool calls in a single response
- Structured JSON output validation
- Separating mock data from agent logic (testability)

---

## Next

→ [Exercise 03 — Multi-Agent Pipeline](../03-multi-agent-pipeline/README.md)
