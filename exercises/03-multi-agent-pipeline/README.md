# Exercise 03 — Multi-Agent Pipeline

## Goal

Build an orchestrator that delegates to two specialised subagents. By the end of this exercise you will:

- Implement the orchestrator-worker pattern
- Understand how to define a `spawn_agent` tool
- Pass context between agents safely
- Run workers in parallel

## Time Estimate

~60 minutes

## The Task

Build a **content intelligence pipeline** that analyses customer feedback:

```
Feedback text
     │
     ▼
ORCHESTRATOR
  ├──► SENTIMENT AGENT  (classifies tone, identifies key themes)
  ├──► ACTION AGENT     (extracts action items and assigns priority)
  └──► Merges results → structured report
```

---

## Architecture Decisions to Notice

1. **The orchestrator does not do domain work.** It only plans and delegates. The classification logic lives in the workers.
2. **Workers receive self-contained task strings.** The orchestrator formats the task with all necessary context before calling `spawn_agent`.
3. **Workers return structured JSON.** The orchestrator can parse and merge results deterministically.
4. **The orchestrator validates worker output.** It does not assume the worker returned valid data.

---

## Instructions

1. Read `pipeline.py` — study how the `AgentWorker` class isolates each subagent's tools and system prompt
2. Run: `python pipeline.py`
3. Try changing the sample feedback to test different scenarios
4. Complete the challenges

---

## Challenges

### Challenge A — Add a third worker
Add a `PriorityAgent` that reads the merged report and assigns an overall business priority score (1-5) with justification. The orchestrator calls it after merging the first two workers' results.

### Challenge B — Parallel execution
The sentiment and action agents are independent. Run them in parallel using `asyncio.gather`. Measure the wall-clock time improvement.

### Challenge C — Error recovery
Make `SentimentAgent` fail 50% of the time (add `random.random() < 0.5: raise RuntimeError`). Add retry logic in the orchestrator: if a worker fails, retry once before giving up. If the retry also fails, produce a partial report with a `"worker_failed"` flag.

### Challenge D — Correlation IDs
Add a `run_id = uuid.uuid4()` that is passed to every worker call and included in every log line. Print a summary showing all log lines grouped by `run_id`.

---

## Key Concepts Practiced

- Orchestrator-worker architecture
- Subagent isolation (each has its own system prompt and tool set)
- Safe context passing between agents
- Structured inter-agent communication

---

## Next

→ [Exercise 04 — Enterprise Workflow with HITL](../04-enterprise-workflow/README.md)
