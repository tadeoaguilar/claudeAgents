# Exercise 05 — Observability

## Goal

Instrument a multi-turn agent with structured logging, metrics, and cost tracking. By the end of this exercise you will:

- Emit structured JSON logs for every agent event
- Track per-run and per-turn metrics
- Compute accurate API cost per run
- Build a summary report from accumulated logs

## Time Estimate

~45 minutes

## The Task

Wrap the research agent from Exercise 02 with a full observability layer:

- Every model call produces a `model_call` log event
- Every tool execution produces a `tool_call` log event
- Every agent run produces a `run_complete` log event with aggregated metrics
- After several runs, generate a cost and performance summary from the log file

---

## Instructions

1. Run: `python monitored_agent.py`
2. Inspect `agent_runs.jsonl` — each line is a structured JSON event
3. Run `python summarise_logs.py` to generate a cost and performance report
4. Complete the challenges

---

## Challenges

### Challenge A — Cache hit rate
The system prompt is cached. Parse the `cache_read_input_tokens` from each `model_call` event. Compute the cache hit rate: what % of input tokens were served from cache? (Target: >60% for a warmed system prompt)

### Challenge B — Anomaly detection
After logging 10+ runs, add a check in `summarise_logs.py` that flags any run where:
- Cost was more than 2x the median cost
- Duration was more than 2x the median duration
- Turn count was more than 3x the median

Print flagged runs with a `[WARNING]` marker.

### Challenge C — Per-tool latency
Track `duration_ms` per tool call in the log. After several runs, compute the average latency per tool name. Which tool is the slowest? Add a `p95_latency_ms` column to the summary.

### Challenge D — Dashboard
Use `rich` to render a live dashboard (updating every 2 seconds) showing:
- Total runs today
- Success rate
- Average cost per run
- Top 3 slowest runs

---

## Key Concepts Practiced

- Structured JSONL logging
- Token and cost accounting per API call
- Aggregated reporting from logs
- The difference between application logs and agent-specific metrics

---

## Exercises Complete!

You have built:
1. A basic agentic loop (Ex 01)
2. A multi-tool research agent (Ex 02)
3. An orchestrator-worker pipeline (Ex 03)
4. An enterprise workflow with HITL (Ex 04)
5. An instrumented, observable agent (Ex 05)

→ Proceed to the [examples/](../../examples/) directory for complete, production-close reference implementations.
