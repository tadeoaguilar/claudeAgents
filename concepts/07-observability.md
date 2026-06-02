# Concept 07 — Observability: Logging, Metrics, Tracing, and Cost Control

## Why Observability Is Different for Agents

Traditional application observability answers: did the code execute correctly?

Agent observability must answer additional questions:
- Did the agent understand the goal correctly?
- Did it choose the right tools in the right order?
- Did it hallucinate or make an error in reasoning?
- Is it getting more expensive over time?
- How do its decisions compare to human decisions?

You need the full picture: the model's reasoning, not just function call success/failure.

---

## The Three Pillars for Agents

### 1. Structured Logging

Every agent event should produce a structured log record (JSON, not free text). This enables:
- Querying by tenant, user, model version, tool, cost
- Automated anomaly detection
- Cost attribution to features and teams

```python
import json
import logging
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, asdict, field
from typing import Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agent")

@dataclass
class AgentRunLog:
    run_id: str
    agent_name: str
    model: str
    goal: str
    status: str              # "success" | "failure" | "timeout" | "hitl_rejected"
    total_input_tokens: int
    total_output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    estimated_cost_usd: float
    duration_ms: float
    turn_count: int
    tool_call_count: int
    tenant_id: str | None = None
    user_id: str | None = None
    error: str | None = None
    tags: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

def compute_cost(
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
    model: str = "claude-opus-4-8"
) -> float:
    # Approximate prices (USD per 1M tokens, mid-2025)
    PRICING = {
        "claude-opus-4-8": {
            "input": 15.00, "output": 75.00,
            "cache_write": 18.75, "cache_read": 1.50
        },
        "claude-sonnet-4-6": {
            "input": 3.00, "output": 15.00,
            "cache_write": 3.75, "cache_read": 0.30
        },
        "claude-haiku-4-5-20251001": {
            "input": 0.80, "output": 4.00,
            "cache_write": 1.00, "cache_read": 0.08
        },
    }
    p = PRICING.get(model, PRICING["claude-opus-4-8"])
    return (
        input_tokens        * p["input"]        / 1_000_000 +
        output_tokens       * p["output"]       / 1_000_000 +
        cache_write_tokens  * p["cache_write"]  / 1_000_000 +
        cache_read_tokens   * p["cache_read"]   / 1_000_000
    )

def log_agent_run(run_log: AgentRunLog) -> None:
    logger.info(json.dumps(asdict(run_log)))
```

### 2. Metrics

Track aggregated signals over time. Push to your metrics system (Prometheus, CloudWatch, Datadog):

```python
from collections import defaultdict
import threading

class AgentMetrics:
    def __init__(self):
        self._lock = threading.Lock()
        self._counters: dict[str, float] = defaultdict(float)
        self._histograms: dict[str, list[float]] = defaultdict(list)

    def increment(self, name: str, value: float = 1.0, tags: dict | None = None) -> None:
        key = self._make_key(name, tags)
        with self._lock:
            self._counters[key] += value

    def record(self, name: str, value: float, tags: dict | None = None) -> None:
        key = self._make_key(name, tags)
        with self._lock:
            self._histograms[key].append(value)

    def _make_key(self, name: str, tags: dict | None) -> str:
        if not tags:
            return name
        tag_str = ",".join(f"{k}={v}" for k, v in sorted(tags.items()))
        return f"{name}[{tag_str}]"

metrics = AgentMetrics()

# In your agent loop:
def record_run_metrics(run_log: AgentRunLog) -> None:
    tags = {"agent": run_log.agent_name, "model": run_log.model, "status": run_log.status}
    if run_log.tenant_id:
        tags["tenant"] = run_log.tenant_id

    metrics.increment("agent.runs.total", tags=tags)
    metrics.record("agent.run.duration_ms", run_log.duration_ms, tags=tags)
    metrics.record("agent.run.cost_usd", run_log.estimated_cost_usd, tags=tags)
    metrics.record("agent.run.turns", run_log.turn_count, tags=tags)
    metrics.record("agent.run.tool_calls", run_log.tool_call_count, tags=tags)
    metrics.record("agent.tokens.input", run_log.total_input_tokens, tags=tags)
    metrics.record("agent.tokens.output", run_log.total_output_tokens, tags=tags)

    if run_log.status != "success":
        metrics.increment("agent.runs.failed", tags=tags)
```

**Key metrics to alert on:**

| Metric | Alert Condition |
|---|---|
| `agent.runs.failed` rate | >5% over 5 minutes |
| `agent.run.cost_usd` p99 | >2x baseline (anomaly) |
| `agent.run.duration_ms` p95 | >SLO threshold (e.g., 30s) |
| `agent.runs.total` by tenant | Sudden spike (possible abuse) |
| `agent.tokens.input` trend | Week-over-week growth >20% |

### 3. Distributed Tracing

For multi-agent systems, correlate all events in a single run using a `run_id`:

```python
import contextvars

_run_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("run_id", default=None)
_parent_run_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("parent_run_id", default=None)

@contextmanager
def trace_agent_run(agent_name: str, parent_run_id: str | None = None):
    run_id = str(uuid.uuid4())
    _run_id.set(run_id)
    _parent_run_id.set(parent_run_id)

    logger.info(json.dumps({
        "event": "agent_run_start",
        "run_id": run_id,
        "parent_run_id": parent_run_id,
        "agent": agent_name,
        "timestamp": time.time(),
    }))

    try:
        yield run_id
    finally:
        logger.info(json.dumps({
            "event": "agent_run_end",
            "run_id": run_id,
            "agent": agent_name,
            "timestamp": time.time(),
        }))
```

Usage in an orchestrator:

```python
with trace_agent_run("orchestrator") as orchestrator_run_id:
    # The orchestrator spawns subagents, passing the run_id for correlation
    research_result = spawn_agent(
        task="Research Q3 revenue trends",
        agent_type="research",
        parent_run_id=orchestrator_run_id  # Link child to parent
    )
```

This lets you reconstruct the full causal chain:
```
orchestrator (run_id: abc)
  └── research-agent (run_id: def, parent: abc)
  └── writer-agent   (run_id: ghi, parent: abc)
```

---

## Monitoring Dashboard: What to Build

A production agent dashboard should show, per time window:

**Overview Tab**
- Total runs (success / failure / timeout)
- Average cost per run (and trend)
- Average latency p50/p95 (and trend)
- Active runs right now

**Cost Tab**
- Cost by agent type
- Cost by tenant (for multi-tenant deployments)
- Cache hit rate (goal: >60% for production prompts)
- Token distribution: input vs. output vs. cache

**Quality Tab**
- Task completion rate from evals
- HITL trigger rate (rising rate may indicate the agent is becoming uncertain)
- Tool call error rate per tool
- Hallucination rate from spot-check sampling

**Per-Tenant Tab**
- Cost consumed vs. quota
- Run count vs. rate limit
- P1 incidents

---

## Prompt Regression Detection

When you change a prompt, run your eval suite and compare metrics automatically:

```python
def compare_prompt_versions(old_version: str, new_version: str, eval_suite: list) -> dict:
    old_results = run_eval_suite(prompt_version=old_version, cases=eval_suite)
    new_results = run_eval_suite(prompt_version=new_version, cases=eval_suite)

    comparison = {
        "task_completion_rate": {
            "old": old_results["completion_rate"],
            "new": new_results["completion_rate"],
            "delta": new_results["completion_rate"] - old_results["completion_rate"],
        },
        "avg_cost_usd": {
            "old": old_results["avg_cost"],
            "new": new_results["avg_cost"],
            "delta": new_results["avg_cost"] - old_results["avg_cost"],
        },
        "schema_compliance_rate": {
            "old": old_results["schema_compliance"],
            "new": new_results["schema_compliance"],
            "delta": new_results["schema_compliance"] - old_results["schema_compliance"],
        },
    }

    # Fail if new version regresses on any key metric
    if comparison["task_completion_rate"]["delta"] < -0.02:
        raise PromptRegressionError("New prompt regresses task completion by >2%")
    if comparison["schema_compliance_rate"]["delta"] < 0:
        raise PromptRegressionError("New prompt regresses schema compliance")

    return comparison
```

---

## Cost Control Strategies

### 1. Prompt Caching (Highest Impact)

For a 5,000-token system prompt called 10,000 times/day on Opus 4.8:

| Approach | Daily Cost |
|---|---|
| No caching | 5,000 × 10,000 × $15/1M = **$750/day** |
| With caching (cache hit rate 80%) | $750 × 0.2 + ($750 × 0.8 × $1.50/$15) = **$210/day** |
| Savings | **$540/day ($197K/year)** |

Enable caching by marking your static system prompt blocks:
```python
system=[{
    "type": "text",
    "text": SYSTEM_PROMPT,
    "cache_control": {"type": "ephemeral"}
}]
```

### 2. Model Selection by Task Complexity

Not every task needs Opus. Use a model routing layer:

```python
def select_model(task_complexity: str) -> str:
    return {
        "simple":  "claude-haiku-4-5-20251001",  # Classification, extraction, formatting
        "medium":  "claude-sonnet-4-6",           # Analysis, summarisation, drafting
        "complex": "claude-opus-4-8",             # Multi-step reasoning, planning, evaluation
    }[task_complexity]
```

### 3. Batch API for Non-Real-Time Workloads

The Batch API processes requests asynchronously with a 50% cost discount — ideal for nightly report generation, document processing, bulk analysis:

```python
batch_request = client.messages.batches.create(
    requests=[
        {
            "custom_id": f"report-{tenant_id}",
            "params": {
                "model": "claude-opus-4-8",
                "max_tokens": 4096,
                "messages": [{"role": "user", "content": f"Generate Q3 report for tenant {tenant_id}"}]
            }
        }
        for tenant_id in tenant_list
    ]
)
```

### 4. Output Length Control

Every extra output token costs 5x more than input. Keep outputs tight:
- Set appropriate `max_tokens` (don't default to 8192 for a classification task)
- Instruct the agent to be concise: "Return only the JSON object, no preamble or explanation"
- Use streaming to detect unexpectedly long outputs early and interrupt

### 5. Tool Result Compression

Tool results accumulate in the context window. Compress them before appending:

```python
def compress_tool_result(raw_result: str, max_chars: int = 2000) -> str:
    if len(raw_result) <= max_chars:
        return raw_result
    # Summarise long results before adding to context
    summary = summarise_with_claude(raw_result, max_tokens=300)
    return f"[Compressed: {len(raw_result)} chars → summary]\n{summary}"
```

---

## Incident Response for Agent Issues

| Symptom | Likely Cause | First Action |
|---|---|---|
| Error rate spike | API error or tool failure | Check tool health; implement retry |
| Cost spike | Prompt regression causing longer outputs | Compare prompt version; roll back |
| Latency spike | Context size growing; caching degraded | Check token counts; verify cache headers |
| Hallucination reports | Model version change; prompt drift | Pin model; run eval suite; compare |
| HITL trigger rate rising | Agent confidence falling; new input distribution | Add evals for new patterns; tune prompt |
| Agent stuck in loop | Missing stop condition; tool always failing | Add iteration cap; fix tool; add fallback |

---

## Summary Checklist

**Logging**
- [ ] Every agent run produces a structured JSON log with run_id, model, cost, status
- [ ] Every tool call logged with input, output, duration, error
- [ ] Logs shipped to central store with 90-day retention

**Metrics**
- [ ] Run success rate, cost, latency tracked per agent type and tenant
- [ ] Alerts configured for >5% error rate, cost anomaly, latency SLO breach

**Tracing**
- [ ] run_id propagated through all subagent calls
- [ ] Parent-child relationships stored for multi-agent runs

**Cost**
- [ ] Prompt caching enabled for all static system prompts
- [ ] Model selection tuned per task complexity
- [ ] Per-tenant cost budget enforced and alerted

**Quality**
- [ ] Eval suite runs in CI on every prompt or agent code change
- [ ] Prompt regression detection blocks bad promotions

---

## Next Steps

You have completed the concepts. Proceed to the exercises to put these ideas into practice:

→ [Exercise 01 — Hello Agent](../exercises/01-hello-agent/README.md)
