# Concept 06 — Deployment Lifecycle: From Prototype to Production

## The Five Stages of Agent Deployment

```
PROTOTYPE ──► EVALUATION ──► STAGING ──► CANARY ──► PRODUCTION
```

Each stage has different success criteria, different audiences, and different risks.

---

## Stage 1: Prototype

**Goal**: Prove the agent can do the task at all.

**Audience**: The engineer building it.

**Characteristics**:
- Hardcoded inputs and outputs
- No error handling
- Single model version
- No observability
- Costs tracked loosely

**Graduation criteria**: The agent completes 5 representative tasks correctly in manual testing.

**Anti-patterns to avoid at this stage**:
- Premature optimisation of prompts
- Building multi-agent architecture before a single agent works
- Adding production-grade infrastructure

---

## Stage 2: Evaluation (Evals)

**Goal**: Measure quality rigorously across a representative sample. This is the most important and most skipped stage.

**Audience**: The engineer + stakeholders who define "correct".

### Building an Eval Suite

An eval is a test with:
- A fixed input
- A defined success criterion (not "does it look right?")
- A deterministic or consistent grading mechanism

```python
from dataclasses import dataclass

@dataclass
class EvalCase:
    name: str
    input: str
    context: dict
    expected_output_schema: dict    # JSON schema the output must match
    success_criteria: list[str]     # Plain-language criteria for LLM-graded eval

EVAL_SUITE = [
    EvalCase(
        name="q3_revenue_by_region",
        input="What was total revenue by region in Q3 2025?",
        context={"tenant_id": "acme-corp"},
        expected_output_schema=REVENUE_ANALYSIS_OUTPUT_SCHEMA,
        success_criteria=[
            "Output is valid JSON",
            "All four regions (AMER, EMEA, APAC, LATAM) are present",
            "Revenue figures are positive numbers",
            "Percentages sum to approximately 100",
        ]
    ),
    EvalCase(
        name="missing_data_handled",
        input="What was revenue by region in Q3 2023?",
        context={"tenant_id": "acme-corp"},
        expected_output_schema=REVENUE_ANALYSIS_OUTPUT_SCHEMA,
        success_criteria=[
            "Agent reports that data is unavailable for 2023",
            "Agent does NOT fabricate figures",
            "Response includes an anomalies field explaining the gap",
        ]
    ),
]
```

### LLM-as-Judge Grading

For criteria that require judgement, use a grader model:

```python
def grade_with_llm(case: EvalCase, actual_output: str) -> dict:
    grader_prompt = f"""You are an expert evaluator for AI agent outputs.

Evaluate the following agent output against the success criteria.
For each criterion, return pass (true) or fail (false) with a brief reason.

Input to agent: {case.input}
Agent output: {actual_output}

Success criteria:
{json.dumps(case.success_criteria, indent=2)}

Return JSON: {{"results": [{{"criterion": str, "pass": bool, "reason": str}}]}}"""

    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=1024,
        messages=[{"role": "user", "content": grader_prompt}]
    )
    return json.loads(response.content[0].text)
```

### Eval Metrics to Track

| Metric | Definition | Target |
|---|---|---|
| Task completion rate | % of evals where agent produces any valid output | >95% |
| Schema compliance rate | % of outputs matching the expected JSON schema | 100% |
| Factual accuracy | % of facts in output verified against ground truth | >90% |
| Hallucination rate | % of outputs containing fabricated facts | <2% |
| Average token cost | Tokens consumed per eval run | Set budget |
| Average latency | Wall-clock time per eval run | Set SLO |
| HITL gate accuracy | % of HITL triggers that were correct (not false alarms) | >80% |

**Graduation criteria**: >90% task completion, 0% schema violations, <5% hallucination rate on representative eval suite.

---

## Stage 3: Staging

**Goal**: Validate the agent works in a production-equivalent environment with real infrastructure but no real users.

**Audience**: QA team, stakeholders, security team.

**Characteristics**:
- Production model version pinned
- Real databases (staging mirror)
- Full observability stack running
- Load testing with realistic concurrency
- Security review completed

### Environment Configuration

Use environment variables to switch between environments:

```python
import os
from enum import Enum

class Environment(Enum):
    LOCAL   = "local"
    STAGING = "staging"
    PROD    = "production"

CURRENT_ENV = Environment(os.getenv("APP_ENV", "local"))

CONFIG = {
    Environment.LOCAL: {
        "database_url": "sqlite:///local.db",
        "model":        "claude-haiku-4-5-20251001",   # Cheaper for local dev
        "max_cost_per_run_usd": 0.10,
        "require_hitl": False,
    },
    Environment.STAGING: {
        "database_url": os.getenv("STAGING_DB_URL"),
        "model":        "claude-opus-4-8",
        "max_cost_per_run_usd": 1.00,
        "require_hitl": True,
    },
    Environment.PROD: {
        "database_url": os.getenv("PROD_DB_URL"),
        "model":        "claude-opus-4-8",
        "max_cost_per_run_usd": 5.00,
        "require_hitl": True,
    },
}

def get_config() -> dict:
    return CONFIG[CURRENT_ENV]
```

**Graduation criteria**: All evals pass in staging environment, load test passes SLOs, security review signed off.

---

## Stage 4: Canary

**Goal**: Validate in production with a small fraction of real traffic before full rollout.

**Audience**: Real users (small %).

**Pattern**: Route 5% of requests to the new agent version; route 95% to the old version. Compare metrics. Promote if metrics match or improve.

```python
import random

def route_request(request: dict) -> str:
    """Route to canary (5%) or stable (95%) agent version."""
    if random.random() < 0.05:
        return run_agent_v2(request)  # Canary
    return run_agent_v1(request)       # Stable
```

**What to compare**:
- Error rate (canary vs. stable)
- Task completion rate
- User satisfaction (thumbs up/down, escalation rate)
- Token cost per request
- Latency p50, p95, p99

**Graduation criteria**: Canary metrics match or beat stable for 24h+ with no P1 incidents.

---

## Stage 5: Production

**Goal**: Serve all traffic reliably at scale.

**Operational requirements**:
- On-call rotation for agent incidents
- Runbook for common failure modes
- Automated rollback trigger (if error rate spikes, route to previous version)
- Model version pinned (never `latest` in production)
- Prompt versioned in a config store, not hardcoded
- Cost budgets per tenant with alerting

### Model Version Pinning

```python
# WRONG — never do this in production
response = client.messages.create(model="claude-latest", ...)

# RIGHT — pin to a specific model version
PRODUCTION_MODEL = "claude-opus-4-8"
response = client.messages.create(model=PRODUCTION_MODEL, ...)
```

Pin your model in a config file that is tracked in version control:

```yaml
# config/production.yml
agent:
  model: "claude-opus-4-8"
  max_tokens: 4096
  temperature: 1
  max_iterations: 10
  token_budget_per_run: 50000
```

### Prompt Versioning

Store prompts in your config store or database, not hardcoded in your application code:

```python
def get_system_prompt(version: str = "latest") -> str:
    return prompt_store.get(f"revenue-analysis-agent:{version}")

# In production, pin the version
PROMPT_VERSION = os.getenv("AGENT_PROMPT_VERSION", "v3.2")
system_prompt = get_system_prompt(PROMPT_VERSION)
```

This lets you:
- Roll back a bad prompt without a code deployment
- A/B test prompt variants
- See exactly which prompt produced which output in the audit log

---

## CI/CD for Agents

Add agent evals to your CI/CD pipeline so regressions are caught before deployment:

```yaml
# .github/workflows/agent-eval.yml
name: Agent Evaluation

on:
  pull_request:
    paths:
      - 'agents/**'
      - 'skills/**'
      - 'prompts/**'

jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run eval suite
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          APP_ENV: staging
        run: |
          pip install -r requirements.txt
          python -m pytest evals/ -v --tb=short
      - name: Check cost budget
        run: python scripts/check_eval_cost.py --max-usd 5.00
```

---

## Prompt Engineering Best Practices for Production

1. **Write prompts for the model version you are using** — prompts tuned for Haiku may not be optimal for Opus, and vice versa
2. **Version your prompts with semantic versioning** — bump minor for phrasing changes, major for behaviour changes
3. **Test regression before promoting** — run the full eval suite against any prompt change
4. **Use XML tags for structure** — `<context>`, `<instructions>`, `<examples>`, `<output_format>` improve parsing reliability
5. **Front-load critical instructions** — the model attends more strongly to instructions at the beginning of the system prompt
6. **Repeat key constraints** — for safety-critical constraints, state them in both the system prompt and at the end of the user message

---

## Next

→ [Concept 07 — Observability: Logging, Metrics, Tracing, and Cost Control](./07-observability.md)
