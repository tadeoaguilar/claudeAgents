# Exercise 06: Capstone — Market Research Intelligence Pipeline

> **Capstone exercise.** This project combines every major pattern from the repo: tools, skills, multi-agent pipelines, HITL gates, and observability — in a single runnable system.

---

## What You Will Build

A **Market Research Intelligence Pipeline** that accepts a company or topic query and produces a structured investment brief:

```
$ python pipeline.py "Tesla electric vehicles"
```

The pipeline runs five stages internally:

```
┌─────────────────────────────────────────────────────────────────┐
│                        ORCHESTRATOR                             │
│  "Plan research strategy, dispatch workers, aggregate results"  │
└────────────────────────┬────────────────────────────────────────┘
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
   ┌───────────┐  ┌────────────┐  ┌───────────────┐
   │ NewsAgent │  │ Sentiment  │  │  Financials   │
   │           │  │   Agent    │  │    Agent      │
   │ search_   │  │ analyze_   │  │ get_financial │
   │ news      │  │ sentiment  │  │ _signals      │
   │ filter_by │  │ get_social │  │               │
   │ _date     │  │ _metrics   │  │               │
   └─────┬─────┘  └─────┬──────┘  └───────┬───────┘
         └───────────────┼─────────────────┘
                         ▼
              ┌──────────────────────┐
              │       SKILLS         │
              │  generate_executive_ │
              │  summary             │
              │  classify_risk       │
              └──────────┬───────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │    HITL GATE         │
              │  (if risk > 0.70)    │
              │  human y/n approval  │
              └──────────┬───────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │     FINAL REPORT     │
              │  report_<id>.md      │
              │  pipeline_runs.jsonl │
              └──────────────────────┘
```

---

## Concepts Covered

| What you build | Concept from repo |
|---|---|
| Tool schemas + `execute_tool()` dispatcher | [concepts/02-agent-architecture.md](../../concepts/02-agent-architecture.md) |
| `AgentWorker` base class with agentic loop | [concepts/02-agent-architecture.md](../../concepts/02-agent-architecture.md) |
| Three specialized worker agents | [concepts/03-subagents-orchestration.md](../../concepts/03-subagents-orchestration.md) |
| `SKILL_REGISTRY` + `invoke_skill()` | [concepts/04-skills.md](../../concepts/04-skills.md) |
| HITL gate with `ApprovalRequest` | [concepts/05-enterprise-patterns.md](../../concepts/05-enterprise-patterns.md) |
| `PipelineTracer`, `SpanContext`, JSONL logs | [concepts/07-observability.md](../../concepts/07-observability.md) |

---

## Prerequisites

- Python 3.11+
- Working virtual environment from the repo root: `source .venv/bin/activate`
- `ANTHROPIC_API_KEY` set in `.env` or your shell
- No extra packages — everything is already in `requirements.txt`

---

## Project Layout

Create the directory and six empty files now. You will fill each one in the corresponding Part below.

```bash
cd exercises/06-capstone-pipeline

touch observability.py
touch tools.py
touch agents.py
touch skills.py
touch hitl.py
touch pipeline.py
```

Final structure when done:

```
06-capstone-pipeline/
├── README.md           ← this file
├── observability.py    ← Part 1: tracer, spans, structured log writer
├── tools.py            ← Part 2: tool schemas + mock implementations
├── agents.py           ← Part 3: AgentWorker base + 3 specialized workers
├── skills.py           ← Part 4: skill registry + 2 skill functions
├── hitl.py             ← Part 5: approval request + gate function
└── pipeline.py         ← Part 6: orchestrator + main entry point
```

---

## Part 1 — Observability Foundation

> Build this **first**. Every agent, tool call, and skill invocation will emit a log event through this module. This is the equivalent of adding instrumentation before you write the application code.

**Concepts:** [concepts/07-observability.md](../../concepts/07-observability.md) — The Three Pillars, Distributed Tracing, AgentRunLog

### What you're building

Three small pieces:

1. **`SpanContext`** — a dataclass that tracks a single unit of work (one agent run, one pipeline run). Stores start/end time so you can compute latency.
2. **`PipelineTracer`** — owns a `run_id` and accumulates `TokenUsage` across all agents so you can report total pipeline cost.
3. **`write_log_event()`** — appends a JSON line to `pipeline_runs.jsonl`. This is your structured log sink.

### Write `observability.py`

```python
# observability.py
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

LOG_FILE = Path("pipeline_runs.jsonl")

# ── Span ─────────────────────────────────────────────────────────

@dataclass
class SpanContext:
    """Tracks one unit of work: an agent run or the full pipeline."""
    run_id: str
    agent_name: str
    span_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    parent_span_id: Optional[str] = None
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None

    def elapsed_ms(self) -> float:
        if self.end_time is None:
            return 0.0
        return (self.end_time - self.start_time) * 1000

# ── Token usage + cost ────────────────────────────────────────────

@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    # Sonnet 4.6 pricing per 1 M tokens (update if you change MODEL)
    _INPUT_PRICE   = 3.00
    _OUTPUT_PRICE  = 15.00
    _CR_PRICE      = 0.30
    _CW_PRICE      = 3.75

    def total_cost_usd(self) -> float:
        return (
            self.input_tokens  * self._INPUT_PRICE  / 1_000_000
            + self.output_tokens * self._OUTPUT_PRICE / 1_000_000
            + self.cache_read_tokens  * self._CR_PRICE / 1_000_000
            + self.cache_write_tokens * self._CW_PRICE / 1_000_000
        )

# ── Tracer ────────────────────────────────────────────────────────

class PipelineTracer:
    """One instance per pipeline run. Accumulates cost across all agents."""

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.total_usage = TokenUsage()

    def span(self, agent_name: str, parent_span_id: Optional[str] = None) -> SpanContext:
        return SpanContext(
            run_id=self.run_id,
            agent_name=agent_name,
            parent_span_id=parent_span_id,
        )

    def record_usage(self, usage: TokenUsage) -> None:
        self.total_usage.input_tokens  += usage.input_tokens
        self.total_usage.output_tokens += usage.output_tokens
        self.total_usage.cache_read_tokens  += usage.cache_read_tokens
        self.total_usage.cache_write_tokens += usage.cache_write_tokens

# ── Log writer ────────────────────────────────────────────────────

def write_log_event(event_type: str, data: dict) -> None:
    """Append one structured JSON line to pipeline_runs.jsonl."""
    event = {"timestamp": time.time(), "event_type": event_type, **data}
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(event) + "\n")
```

### Test Part 1

Run this snippet directly to confirm the log file is written:

```bash
python - <<'EOF'
from observability import PipelineTracer, TokenUsage, write_log_event

tracer = PipelineTracer(run_id="test-001")
span   = tracer.span("test_agent")

write_log_event("test_event", {
    "run_id": span.run_id,
    "span_id": span.span_id,
    "message": "observability layer is working",
})

tracer.record_usage(TokenUsage(input_tokens=500, output_tokens=120))
print(f"Total cost so far: ${tracer.total_usage.total_cost_usd():.4f}")
print("Check pipeline_runs.jsonl for the log entry.")
EOF
```

Expected output:
```
Total cost so far: $0.0033
Check pipeline_runs.jsonl for the log entry.
```

---

## Part 2 — Tool Definitions

> Tools are what give agents the ability to _do_ things. In this exercise, all tools have **mock implementations** so the pipeline runs without any external API keys.

**Concepts:** [concepts/02-agent-architecture.md](../../concepts/02-agent-architecture.md) — tool schemas, tool_use blocks, parallel tool calls

### What you're building

Two things in one file:

1. **`TOOLS`** — a list of tool schema dicts in the exact format the Claude API expects. These are passed to `client.messages.create(tools=TOOLS)`.
2. **`execute_tool(name, input)`** — a dispatcher that routes tool calls to their Python implementations. Every call returns realistic-looking mock data.

The five tools:

| Tool name | What it simulates |
|---|---|
| `search_news` | News article search with title, source, date |
| `filter_by_date` | Filters articles to the last N days |
| `analyze_sentiment` | Returns sentiment score 0.0–1.0 |
| `get_social_metrics` | Social media mention count and trend |
| `get_financial_signals` | Stock trend, analyst ratings, P/E ratio |

### Write `tools.py`

```python
# tools.py
import random
from typing import Any

# ── Tool schemas (passed to client.messages.create) ───────────────

TOOLS = [
    {
        "name": "search_news",
        "description": "Search recent news articles about a company or topic.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query":       {"type": "string",  "description": "Search query — company name or topic"},
                "max_results": {"type": "integer", "description": "Max articles to return (default 5)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "filter_by_date",
        "description": "Filter a list of articles to only those published within the last N days.",
        "input_schema": {
            "type": "object",
            "properties": {
                "articles":  {"type": "array",   "description": "List of article objects from search_news"},
                "days_back": {"type": "integer", "description": "How many days back to include"},
            },
            "required": ["articles", "days_back"],
        },
    },
    {
        "name": "analyze_sentiment",
        "description": "Score the market sentiment expressed in a list of text snippets.",
        "input_schema": {
            "type": "object",
            "properties": {
                "texts":  {"type": "array",  "items": {"type": "string"}, "description": "Texts to analyze"},
                "entity": {"type": "string", "description": "Company or topic being analyzed"},
            },
            "required": ["texts", "entity"],
        },
    },
    {
        "name": "get_social_metrics",
        "description": "Get social media engagement metrics (mentions, sentiment ratio) for a topic.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic":    {"type": "string", "description": "Topic or company to look up"},
                "platform": {
                    "type": "string",
                    "enum": ["twitter", "reddit", "all"],
                    "description": "Which platform to query (default: all)",
                },
            },
            "required": ["topic"],
        },
    },
    {
        "name": "get_financial_signals",
        "description": "Retrieve key financial signals: stock price trend, analyst consensus, and earnings data.",
        "input_schema": {
            "type": "object",
            "properties": {
                "company": {"type": "string", "description": "Company name or stock ticker"},
                "period":  {"type": "string", "description": "Look-back period e.g. '90d' or '30d' (default 90d)"},
            },
            "required": ["company"],
        },
    },
]

# ── Mock implementations ──────────────────────────────────────────
# Return realistic-looking data without any real API calls.

def _search_news(query: str, max_results: int = 5) -> list[dict]:
    articles = [
        {"title": f"{query}: Q4 earnings beat expectations by 12%",              "source": "Bloomberg",   "date": "2024-11-15", "url": "https://bloomberg.com/1"},
        {"title": f"{query} announces major product launch at investor day",      "source": "Reuters",     "date": "2024-11-10", "url": "https://reuters.com/2"},
        {"title": f"Analysts raise {query} price targets after strong guidance",  "source": "CNBC",        "date": "2024-11-08", "url": "https://cnbc.com/3"},
        {"title": f"{query} faces supply-chain pressure in Asia markets",         "source": "FT",          "date": "2024-11-05", "url": "https://ft.com/4"},
        {"title": f"Regulatory scrutiny increases on {query}'s market practices", "source": "WSJ",         "date": "2024-10-30", "url": "https://wsj.com/5"},
        {"title": f"{query} partners with enterprises on AI integration",         "source": "TechCrunch",  "date": "2024-10-25", "url": "https://techcrunch.com/6"},
    ]
    return articles[:max_results]


def _filter_by_date(articles: list, days_back: int) -> list:
    # Mock: all dates are static, so return the first (days_back // 10 + 2) articles
    cutoff = max(1, days_back // 10 + 2)
    return articles[:cutoff]


def _analyze_sentiment(texts: list, entity: str) -> dict:
    seed = sum(ord(c) for c in entity)
    random.seed(seed)
    score = round(random.uniform(0.30, 0.85), 3)
    label = "bullish" if score > 0.60 else "neutral" if score > 0.42 else "bearish"
    return {
        "entity":        entity,
        "overall_score": score,
        "label":         label,
        "article_count": len(texts),
        "breakdown": {
            "positive": int(len(texts) * score),
            "neutral":  1,
            "negative": max(0, len(texts) - int(len(texts) * score) - 1),
        },
    }


def _get_social_metrics(topic: str, platform: str = "all") -> dict:
    seed = sum(ord(c) for c in topic) + 1
    random.seed(seed)
    return {
        "topic":              topic,
        "platform":           platform,
        "mention_count_24h":  random.randint(1_200, 45_000),
        "sentiment_ratio":    round(random.uniform(0.45, 0.80), 3),
        "trending":           random.choice([True, False]),
        "top_hashtags":       [f"#{topic.split()[0]}", "#investing", "#markets"],
    }


def _get_financial_signals(company: str, period: str = "90d") -> dict:
    seed = sum(ord(c) for c in company) + 2
    random.seed(seed)
    return {
        "company":                  company,
        "period":                   period,
        "price_change_pct":         round(random.uniform(-15, 35), 2),
        "analyst_consensus":        random.choice(["Strong Buy", "Buy", "Hold", "Underperform"]),
        "target_upside_pct":        round(random.uniform(-5, 40), 2),
        "earnings_surprise_pct":    round(random.uniform(-8, 18), 2),
        "pe_ratio":                 round(random.uniform(12, 65), 1),
        "institutional_ownership":  round(random.uniform(55, 92), 1),
    }

# ── Dispatcher ────────────────────────────────────────────────────

_DISPATCH = {
    "search_news":          _search_news,
    "filter_by_date":       _filter_by_date,
    "analyze_sentiment":    _analyze_sentiment,
    "get_social_metrics":   _get_social_metrics,
    "get_financial_signals": _get_financial_signals,
}

def execute_tool(tool_name: str, tool_input: dict) -> Any:
    """Route a tool_use block to its implementation."""
    fn = _DISPATCH.get(tool_name)
    if fn is None:
        raise ValueError(f"Unknown tool: {tool_name!r}")
    return fn(**tool_input)
```

### Test Part 2

```bash
python - <<'EOF'
from tools import execute_tool

news = execute_tool("search_news", {"query": "Acme Corp", "max_results": 3})
print(f"News results: {len(news)} articles")
print(f"  First: {news[0]['title']}")

sentiment = execute_tool("analyze_sentiment", {
    "texts": [a["title"] for a in news],
    "entity": "Acme Corp",
})
print(f"Sentiment: {sentiment['label']} ({sentiment['overall_score']})")

financials = execute_tool("get_financial_signals", {"company": "Acme Corp"})
print(f"Analyst consensus: {financials['analyst_consensus']}")
EOF
```

---

## Part 3 — Worker Agents

> Three specialized agents, each with its own system prompt and a subset of tools. They are completely isolated from each other — they don't share memory, context, or tool access.

**Concepts:** [concepts/03-subagents-orchestration.md](../../concepts/03-subagents-orchestration.md) — Worker Isolation, Task Specification; [concepts/02-agent-architecture.md](../../concepts/02-agent-architecture.md) — the canonical agentic loop, Context Management at Scale

### What you're building

**`AgentWorker`** — a base class whose `run()` method is a full agentic loop:

```
while iterations < MAX:
    call Claude with (system_prompt, tools, messages)
    if stop_reason == "end_turn":  break, return result text
    if stop_reason == "tool_use":  execute tools, append results, continue
```

Every call to `run()` automatically:
- Opens a span in the tracer (start time)
- Emits `agent_start` and `agent_end` log events
- Emits a `tool_call` log event for each tool invocation
- Accumulates token usage back into the pipeline tracer

Three subclasses customize only two things: `system_prompt` and `allowed_tools`.

### Write `agents.py`

```python
# agents.py
import json
import os
import time
from typing import Optional

import anthropic
from dotenv import load_dotenv

from observability import PipelineTracer, TokenUsage, write_log_event
from tools import TOOLS, execute_tool

load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Use Haiku for workers: faster and ~10× cheaper than Sonnet.
# Swap to "claude-sonnet-4-6" if you need stronger reasoning.
MODEL = "claude-haiku-4-5-20251001"

# ── Base agent ────────────────────────────────────────────────────

class AgentWorker:
    """
    Runs a single-agent agentic loop with built-in observability.

    Subclasses override:
      - name          (str)  — used in log events
      - system_prompt (str)  — the agent's role and output format
      - allowed_tools (list) — tool names this agent may call
    """

    name:           str       = "base_agent"
    system_prompt:  str       = "You are a helpful assistant."
    allowed_tools:  list[str] = []

    MAX_ITERATIONS = 10

    def __init__(self, tracer: PipelineTracer, parent_span_id: Optional[str] = None):
        self.tracer         = tracer
        self.parent_span_id = parent_span_id

    # ── Public ────────────────────────────────────────────────────

    def run(self, task: str) -> dict:
        """Execute the task and return a result dict."""
        span  = self.tracer.span(self.name, parent_span_id=self.parent_span_id)
        usage = TokenUsage()

        write_log_event("agent_start", {
            "run_id":       span.run_id,
            "span_id":      span.span_id,
            "parent_span":  span.parent_span_id,
            "agent":        self.name,
            "task_preview": task[:120],
        })

        messages    = [{"role": "user", "content": task}]
        result_text = ""
        iterations  = 0

        while iterations < self.MAX_ITERATIONS:
            iterations += 1

            response = client.messages.create(
                model=MODEL,
                max_tokens=2048,
                system=self.system_prompt,
                tools=self._active_tools(),
                messages=messages,
            )

            usage.input_tokens  += response.usage.input_tokens
            usage.output_tokens += response.usage.output_tokens

            if response.stop_reason == "end_turn":
                result_text = next(
                    (b.text for b in response.content if hasattr(b, "text")), ""
                )
                break

            if response.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": response.content})
                tool_results = []

                for block in response.content:
                    if block.type != "tool_use":
                        continue

                    raw_result = execute_tool(block.name, block.input)

                    write_log_event("tool_call", {
                        "run_id":  span.run_id,
                        "span_id": span.span_id,
                        "agent":   self.name,
                        "tool":    block.name,
                        "input":   block.input,
                    })

                    tool_results.append({
                        "type":        "tool_result",
                        "tool_use_id": block.id,
                        "content":     json.dumps(raw_result),
                    })

                messages.append({"role": "user", "content": tool_results})

        span.end_time = time.time()
        self.tracer.record_usage(usage)

        write_log_event("agent_end", {
            "run_id":        span.run_id,
            "span_id":       span.span_id,
            "agent":         self.name,
            "elapsed_ms":    span.elapsed_ms(),
            "iterations":    iterations,
            "input_tokens":  usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cost_usd":      usage.total_cost_usd(),
        })

        return {
            "agent":      self.name,
            "result":     result_text,
            "usage":      usage,
            "elapsed_ms": span.elapsed_ms(),
        }

    # ── Private ───────────────────────────────────────────────────

    def _active_tools(self) -> list[dict]:
        """Return only the tool schemas this agent is allowed to use."""
        return [t for t in TOOLS if t["name"] in self.allowed_tools]


# ── Worker specializations ────────────────────────────────────────

class NewsAgent(AgentWorker):
    name = "news_agent"
    system_prompt = """\
You are a financial news research specialist.

TASK: Search for recent news about the given topic, filter to the last 60 days,
and return a JSON object with exactly these fields:
  - key_events: list of the 3 most important news items, each with:
      { "title": str, "date": str, "source": str, "impact": "positive"|"negative"|"neutral" }
  - overall_narrative: one paragraph (2-3 sentences) summarizing the news landscape

PROCESS:
1. Call search_news to fetch articles.
2. Call filter_by_date with days_back=60 to focus on recent ones.
3. Analyze the filtered articles.
4. Return the JSON object described above. No markdown, no explanation — just JSON.
"""
    allowed_tools = ["search_news", "filter_by_date"]


class SentimentAgent(AgentWorker):
    name = "sentiment_agent"
    system_prompt = """\
You are a market sentiment analyst.

TASK: Analyze market and social sentiment for the given topic and return a JSON object with:
  - sentiment_score: float 0.0 (very bearish) to 1.0 (very bullish)
  - sentiment_label: "bullish" | "neutral" | "bearish"
  - social_momentum: one sentence describing social media activity
  - key_signals: list of 2-3 specific data points that drove your assessment

PROCESS:
1. Call analyze_sentiment with relevant text snippets about the topic.
2. Call get_social_metrics for the topic.
3. Combine both signals into the JSON object above. JSON only — no extra text.
"""
    allowed_tools = ["analyze_sentiment", "get_social_metrics"]


class FinancialsAgent(AgentWorker):
    name = "financials_agent"
    system_prompt = """\
You are a quantitative financial analyst.

TASK: Retrieve and interpret financial signals for the given company and return a JSON object with:
  - financial_health: "strong" | "stable" | "weak"
  - price_momentum:   one sentence on recent price action
  - analyst_view:     one sentence summarizing analyst consensus
  - key_metrics:      dict with the most important numbers from the data

PROCESS:
1. Call get_financial_signals with a 90-day period.
2. Interpret the numbers.
3. Return the JSON object above. JSON only.
"""
    allowed_tools = ["get_financial_signals"]
```

### Context Management at Scale

> **Why this matters.** Every tool call appends two new messages to the `messages` array (one `assistant` turn with the `tool_use` block, one `user` turn with the `tool_result`). Claude re-reads the entire array on every API call, so input tokens grow with each iteration. For an agent that makes 8 tool calls, the 8th call re-sends the context of the first 7 rounds — most of which is raw JSON data the model has already processed. At scale this causes three problems: runaway token costs, slower latency, and eventually hitting the context-window limit.

**The fix: context trimming with a token budget.**

When `input_tokens` from the last response exceeds a threshold, collapse the middle of the conversation history into a short summary and discard the raw turns. The agent retains its task (first message) and the most recent turn (needed for API continuity), but replaces everything in between with a compact summary generated by a cheap, targeted Claude call.

```
BEFORE trim (8 turns, 9 000 tokens):
  [task] [assistant/tool_use] [tool_result] [assistant/tool_use] [tool_result] ...

AFTER trim (3 messages, ~1 500 tokens):
  [task] [summary: "Retrieved 5 articles. Filtered to 3 recent ones. Key events: ..."] [last_tool_result]
```

Add the following to `agents.py`. First, add a class variable to `AgentWorker`:

```python
TOKEN_BUDGET = 6_000  # trim conversation when input tokens exceed this limit
```

Then add two private methods to `AgentWorker` (after `_active_tools`):

```python
    def _trim_context(
        self,
        messages: list,
        last_input_tokens: int,
        run_id: str,
    ) -> list:
        """
        If the conversation is growing past TOKEN_BUDGET, collapse the
        middle turns into a single summary to prevent unbounded context growth.

        Invariants kept:
          - messages[0]  = original user task (always kept verbatim)
          - messages[-2:] = last assistant turn + tool results (required by API)
          - everything in between is summarised and discarded
        """
        if last_input_tokens < self.TOKEN_BUDGET:
            return messages

        # Need at least: task + one middle turn + last two turns to bother trimming
        if len(messages) < 5:
            return messages

        original_task = messages[0]
        last_two      = messages[-2:]
        to_summarise  = messages[1:-2]

        summary = self._summarise_history(to_summarise)

        write_log_event("context_trimmed", {
            "run_id":           run_id,
            "agent":            self.name,
            "tokens_before":    last_input_tokens,
            "turns_collapsed":  len(to_summarise),
        })

        return [
            original_task,
            {
                "role":    "user",
                "content": f"[Summary of prior research]\n{summary}",
            },
            *last_two,
        ]

    def _summarise_history(self, messages: list) -> str:
        """
        Ask Claude (Haiku, small token budget) to compress prior turns
        into a concise bullet-point summary the agent can reason from.
        """
        history_text = "\n".join(
            f"{m['role'].upper()}: {str(m['content'])[:600]}"
            for m in messages
        )
        response = client.messages.create(
            model=MODEL,
            max_tokens=300,
            messages=[{
                "role":    "user",
                "content": (
                    "Summarise the key findings from these agent conversation turns "
                    "in 4-6 bullet points. Include: data already retrieved, "
                    "tool results, and any decisions made. Be concise.\n\n"
                    + history_text
                ),
            }],
        )
        return response.content[0].text
```

Finally, update the `run()` method to call `_trim_context()` after accumulating token usage from each response. Replace this block in `run()`:

```python
            usage.input_tokens  += response.usage.input_tokens
            usage.output_tokens += response.usage.output_tokens
```

With:

```python
            usage.input_tokens  += response.usage.input_tokens
            usage.output_tokens += response.usage.output_tokens

            # Trim context if the conversation history is getting too large
            messages = self._trim_context(
                messages,
                last_input_tokens=response.usage.input_tokens,
                run_id=span.run_id,
            )
```

**Why trim after accumulating, not before the next call?** Because `response.usage.input_tokens` is the most accurate signal — it's the actual count Claude used, not an estimate. Trimming right after you receive it means the next iteration starts clean.

**What to tune:**
- `TOKEN_BUDGET = 6_000` works well for Haiku's 200k context. Raise it for tasks that need longer raw histories; lower it to reduce per-call costs on simple agents.
- The summary prompt targets 4-6 bullets. For tasks with dense JSON payloads (like financial data), increase `max_tokens=300` to 450 so the summary isn't truncated.

**Log events emitted by context trimming:**

When a trim occurs you will see a `context_trimmed` event in `pipeline_runs.jsonl`:

```json
{
  "timestamp": 1720000000.0,
  "event_type": "context_trimmed",
  "run_id": "a3f9d1c02b4e",
  "agent": "news_agent",
  "tokens_before": 7842,
  "turns_collapsed": 4
}
```

Use this to diagnose agents that are making too many tool calls or receiving oversized tool results — both are signals the tool outputs need trimming upstream.

---

### Test Part 3

Run `NewsAgent` standalone to verify the agentic loop works end-to-end:

```bash
python - <<'EOF'
import uuid
from observability import PipelineTracer
from agents import NewsAgent

tracer = PipelineTracer(run_id=uuid.uuid4().hex[:8])
agent  = NewsAgent(tracer=tracer)

result = agent.run("Search for recent news about Acme Corp")

print(f"Agent: {result['agent']}")
print(f"Elapsed: {result['elapsed_ms']:.0f} ms")
print(f"Tokens in/out: {result['usage'].input_tokens} / {result['usage'].output_tokens}")
print(f"Cost: ${result['usage'].total_cost_usd():.4f}")
print()
print("Result preview:")
print(result["result"][:300])
EOF
```

You should see structured JSON returned by the model, plus a new entry in `pipeline_runs.jsonl` for `agent_start`, `tool_call` (×2), and `agent_end`.

To verify context trimming, force the threshold very low so it fires on the first iteration, then check the log:

```bash
python - <<'EOF'
import uuid
from observability import PipelineTracer
from agents import NewsAgent

# Temporarily lower the budget to guarantee a trim on the first tool call
NewsAgent.TOKEN_BUDGET = 1  # any response will exceed 1 token

tracer = PipelineTracer(run_id=uuid.uuid4().hex[:8])
agent  = NewsAgent(tracer=tracer)

result = agent.run("Search for recent news about Acme Corp")
print("Result preview:", result["result"][:200])

import json
from pathlib import Path
events = [json.loads(l) for l in Path("pipeline_runs.jsonl").read_text().splitlines() if l]
trims  = [e for e in events if e["event_type"] == "context_trimmed"]
print(f"\nContext trim events: {len(trims)}")
if trims:
    print(f"  Turns collapsed : {trims[-1]['turns_collapsed']}")
    print(f"  Tokens before   : {trims[-1]['tokens_before']}")

# Reset to production value
NewsAgent.TOKEN_BUDGET = 6_000
EOF
```

---

## Part 4 — Skills

> A **skill** is a named, reusable workflow that operates _above_ a single tool call but _below_ a full agent. Skills in this API context are just Python functions registered in a dict and invoked by name.

**Concepts:** [concepts/04-skills.md](../../concepts/04-skills.md) — Skills vs. Tools vs. Agents, the Skill Registry pattern

### What you're building

- **`SKILL_REGISTRY`** — a `dict[str, Callable]` that maps skill names to functions.
- **`invoke_skill(name, run_id, **kwargs)`** — looks up and calls the function, raising a clear error if the name is unknown.
- **Two skills:**
  - `generate_executive_summary` — synthesizes all agent outputs into a brief with verdict
  - `classify_risk` — returns a risk score (0–1) and identifies top risk factors

Skills make one Claude API call each. They use a structured prompt and expect JSON back.

### Write `skills.py`

```python
# skills.py
import json
import os
from typing import Any, Callable

import anthropic
from dotenv import load_dotenv

from observability import write_log_event

load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Sonnet for skills: they require stronger synthesis than workers.
SKILLS_MODEL = "claude-sonnet-4-6"

# ── Skill implementations ─────────────────────────────────────────

def _generate_executive_summary(run_id: str, research_data: dict) -> dict:
    """
    Synthesize news + sentiment + financial data into an executive brief.
    Returns a dict with: headline, situation, opportunity, watch_items, verdict.
    """
    prompt = f"""\
You are a senior investment analyst writing an executive brief for a portfolio committee.

Given the research data below, produce a JSON object with EXACTLY these fields:
  - headline:    one compelling sentence, max 15 words
  - situation:   2 sentences describing the current state of play
  - opportunity: 1 sentence on the primary upside case
  - watch_items: list of 2-3 risks or factors to monitor
  - verdict:     exactly one of "Favorable" | "Neutral" | "Cautious"

Research data:
{json.dumps(research_data, indent=2)}

Return ONLY valid JSON. No markdown fences, no explanation.
"""

    response = client.messages.create(
        model=SKILLS_MODEL,
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )

    write_log_event("skill_invoke", {
        "run_id":        run_id,
        "skill":         "generate_executive_summary",
        "input_tokens":  response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    })

    text = _strip_fences(response.content[0].text)
    return json.loads(text)


def _classify_risk(run_id: str, research_data: dict) -> dict:
    """
    Classify investment risk level from aggregated research.
    Returns: risk_score, risk_level, primary_risk_factors, mitigating_factors.
    """
    prompt = f"""\
You are a risk management expert advising an investment committee.

Analyze the research data below and return a JSON object with EXACTLY these fields:
  - risk_score:            float from 0.0 (no risk) to 1.0 (extreme risk)
  - risk_level:            exactly one of "Low" | "Medium" | "High" | "Critical"
  - primary_risk_factors:  list of top 3 risk factors (short phrases)
  - mitigating_factors:    list of 2-3 factors that reduce risk (short phrases)

Risk level guidance:
  0.0–0.35 → Low   |   0.35–0.60 → Medium   |   0.60–0.80 → High   |   0.80+ → Critical

Research data:
{json.dumps(research_data, indent=2)}

Return ONLY valid JSON.
"""

    response = client.messages.create(
        model=SKILLS_MODEL,
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )

    write_log_event("skill_invoke", {
        "run_id":        run_id,
        "skill":         "classify_risk",
        "input_tokens":  response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    })

    text = _strip_fences(response.content[0].text)
    return json.loads(text)


def _strip_fences(text: str) -> str:
    """Remove markdown code fences if the model wraps its JSON output."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Drop first line (```json or ```) and last line (```)
        text = "\n".join(lines[1:-1])
    return text.strip()

# ── Registry ──────────────────────────────────────────────────────

SKILL_REGISTRY: dict[str, Callable] = {
    "generate_executive_summary": _generate_executive_summary,
    "classify_risk":              _classify_risk,
}


def invoke_skill(skill_name: str, run_id: str, **kwargs) -> Any:
    """
    Look up and call a skill by name.

    Usage:
        result = invoke_skill("classify_risk", run_id=run_id, research_data={...})
    """
    fn = SKILL_REGISTRY.get(skill_name)
    if fn is None:
        available = list(SKILL_REGISTRY)
        raise ValueError(f"Unknown skill {skill_name!r}. Available: {available}")
    return fn(run_id=run_id, **kwargs)
```

### Test Part 4

```bash
python - <<'EOF'
from skills import invoke_skill

mock_data = {
    "query": "Acme Corp",
    "news": "Strong Q4 earnings and new product pipeline.",
    "sentiment": {"sentiment_score": 0.72, "sentiment_label": "bullish"},
    "financials": {"analyst_consensus": "Buy", "price_change_pct": 18.5},
}

summary = invoke_skill("generate_executive_summary", run_id="test-001", research_data=mock_data)
print("Summary verdict:", summary["verdict"])
print("Headline:", summary["headline"])

risk = invoke_skill("classify_risk", run_id="test-001", research_data=mock_data)
print(f"\nRisk level: {risk['risk_level']} (score: {risk['risk_score']:.2f})")
print("Top risk factor:", risk["primary_risk_factors"][0])
EOF
```

---

## Part 5 — HITL Gate

> Some decisions are too consequential to automate. The HITL (Human-In-The-Loop) gate blocks the pipeline and presents a structured approval request. Only if the operator approves does the report get delivered.

**Concepts:** [concepts/05-enterprise-patterns.md](../../concepts/05-enterprise-patterns.md) — HITL Decision Matrix, ApprovalRequest, gate implementation

### What you're building

- **`ApprovalRequest`** — a dataclass that bundles everything the operator needs to make a decision: run ID, risk score, risk level, headline, reason.
- **`hitl_gate(request)`** — prints the request to the terminal, waits for `y/n`, emits a log event for the decision, and returns `True` (approved) or `False` (rejected).

In production you would swap the `input()` call for a webhook call to Slack, PagerDuty, or a web UI — the interface is the same.

### Write `hitl.py`

```python
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
```

### Test Part 5

Run this to see the gate in action. Type `y` to approve or `n` to reject.

```bash
python - <<'EOF'
from hitl import ApprovalRequest, hitl_gate

req = ApprovalRequest(
    run_id="test-001",
    reason="Risk score 0.82 exceeds threshold 0.70",
    risk_score=0.82,
    risk_level="Critical",
    summary_headline="Acme Corp faces regulatory headwinds after record earnings",
)

approved = hitl_gate(req)
print(f"Gate returned: {approved}")
EOF
```

---

## Part 6 — Orchestrator and Pipeline

> The orchestrator is the brain. It knows the sequence of steps, owns the tracer, dispatches workers, invokes skills, runs the HITL gate if needed, and assembles the final report.

**Concepts:** [concepts/03-subagents-orchestration.md](../../concepts/03-subagents-orchestration.md) — Orchestrator Pattern, Sequential Pipeline; [concepts/05-enterprise-patterns.md](../../concepts/05-enterprise-patterns.md) — Audit Trail

### What you're building

- **`Orchestrator`** — a class that owns the `PipelineTracer` and coordinates the full pipeline in `run_pipeline()`.
- **`main()`** — reads the CLI argument, creates an `Orchestrator`, calls `run_pipeline()`, prints and saves the report, shows a cost summary.

### Write `pipeline.py`

```python
#!/usr/bin/env python3
# pipeline.py
import json
import os
import sys
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

load_dotenv()

from observability import PipelineTracer, write_log_event
from agents import NewsAgent, SentimentAgent, FinancialsAgent
from skills import invoke_skill
from hitl import ApprovalRequest, hitl_gate

RISK_THRESHOLD = 0.70   # Scores above this trigger HITL
console = Console()

# ── Orchestrator ──────────────────────────────────────────────────

class Orchestrator:
    """
    Owns the tracer and coordinates the full research pipeline:
    1. Dispatch three worker agents in sequence.
    2. Apply two skills to synthesize the results.
    3. Run HITL gate if risk score exceeds threshold.
    4. Assemble and save the final report.
    """

    def __init__(self, run_id: str):
        self.run_id  = run_id
        self.tracer  = PipelineTracer(run_id)

    def run_pipeline(self, query: str) -> dict:
        pipeline_start = time.time()

        write_log_event("pipeline_start", {"run_id": self.run_id, "query": query})

        console.print(Panel(
            f"[bold cyan]Market Research Intelligence Pipeline[/bold cyan]\n"
            f"Query : [yellow]{query}[/yellow]\n"
            f"Run ID: {self.run_id}",
            expand=False,
        ))

        # ── Stage 1: Worker agents ─────────────────────────────────
        console.print("\n[bold]Stage 1 — Gathering intelligence[/bold]")

        orch_span = self.tracer.span("orchestrator")

        news_result      = self._run_agent(NewsAgent,      query,                                       orch_span.span_id)
        sentiment_result = self._run_agent(SentimentAgent, f"Analyze market sentiment for: {query}",   orch_span.span_id)
        financials_result= self._run_agent(FinancialsAgent,f"Get financial signals for: {query}",      orch_span.span_id)

        # ── Stage 2: Aggregate ─────────────────────────────────────
        research_data = {
            "query":      query,
            "news":       news_result["result"],
            "sentiment":  sentiment_result["result"],
            "financials": financials_result["result"],
        }

        # ── Stage 3: Skills ────────────────────────────────────────
        console.print("\n[bold]Stage 2 — Applying skills[/bold]")

        summary = invoke_skill(
            "generate_executive_summary",
            run_id=self.run_id,
            research_data=research_data,
        )
        console.print(
            f"  [green]✓[/green] executive_summary — "
            f"verdict: [bold]{summary.get('verdict', '?')}[/bold] | "
            f"headline: [italic]{summary.get('headline', '')[:60]}[/italic]"
        )

        risk = invoke_skill(
            "classify_risk",
            run_id=self.run_id,
            research_data=research_data,
        )
        risk_score = risk.get("risk_score", 0.0)
        console.print(
            f"  [green]✓[/green] classify_risk — "
            f"level: [bold]{risk.get('risk_level', '?')}[/bold] | "
            f"score: {risk_score:.2f}"
        )

        # ── Stage 4: HITL gate (conditional) ──────────────────────
        if risk_score > RISK_THRESHOLD:
            console.print(
                f"\n[bold yellow]Stage 3 — HITL gate[/bold yellow] "
                f"(risk {risk_score:.2f} > threshold {RISK_THRESHOLD})"
            )
            approved = hitl_gate(ApprovalRequest(
                run_id=self.run_id,
                reason=f"Risk score {risk_score:.2f} exceeds threshold {RISK_THRESHOLD}",
                risk_score=risk_score,
                risk_level=risk.get("risk_level", "Unknown"),
                summary_headline=summary.get("headline", ""),
            ))
            if not approved:
                write_log_event("pipeline_end", {
                    "run_id": self.run_id,
                    "status": "rejected",
                    "elapsed_ms": (time.time() - pipeline_start) * 1000,
                })
                return {"status": "rejected", "run_id": self.run_id}

        # ── Stage 5: Assemble and deliver ─────────────────────────
        report = _assemble_report(
            query=query,
            run_id=self.run_id,
            summary=summary,
            risk=risk,
        )

        elapsed = time.time() - pipeline_start

        write_log_event("pipeline_end", {
            "run_id":              self.run_id,
            "status":              "delivered",
            "elapsed_ms":          elapsed * 1000,
            "total_input_tokens":  self.tracer.total_usage.input_tokens,
            "total_output_tokens": self.tracer.total_usage.output_tokens,
            "total_cost_usd":      self.tracer.total_usage.total_cost_usd(),
            "risk_score":          risk_score,
            "verdict":             summary.get("verdict", "Unknown"),
        })

        return {
            "status":        "delivered",
            "report":        report,
            "run_id":        self.run_id,
            "elapsed_s":     elapsed,
            "total_cost_usd": self.tracer.total_usage.total_cost_usd(),
        }

    def _run_agent(self, AgentClass, task: str, parent_span_id: str) -> dict:
        agent  = AgentClass(tracer=self.tracer, parent_span_id=parent_span_id)
        console.print(f"  Running [cyan]{agent.name}[/cyan]...")
        result = agent.run(task)
        console.print(
            f"  [green]✓[/green] {agent.name} — "
            f"{result['elapsed_ms']:.0f} ms | "
            f"{result['usage'].input_tokens + result['usage'].output_tokens} tokens | "
            f"${result['usage'].total_cost_usd():.4f}"
        )
        return result


# ── Report assembly ───────────────────────────────────────────────

def _assemble_report(query: str, run_id: str, summary: dict, risk: dict) -> str:
    verdict_icon = {"Favorable": "🟢", "Neutral": "🟡", "Cautious": "🔴"}.get(summary.get("verdict", ""), "⚪")
    risk_icon    = {"Low": "🟢", "Medium": "🟡", "High": "🟠", "Critical": "🔴"}.get(risk.get("risk_level", ""), "⚪")

    watch_items   = "\n".join(f"- {w}" for w in summary.get("watch_items", []))
    risk_factors  = "\n".join(f"- {r}" for r in risk.get("primary_risk_factors", []))
    mitigators    = "\n".join(f"- {m}" for m in risk.get("mitigating_factors", []))

    return f"""\
# Market Intelligence Report

**Query:** {query}
**Run ID:** {run_id}

---

## Executive Summary

**Headline:** {summary.get('headline', '')}
**Verdict:** {verdict_icon} {summary.get('verdict', '')}

{summary.get('situation', '')}

{summary.get('opportunity', '')}

### Items to Watch
{watch_items}

---

## Risk Assessment

**Risk Level:** {risk_icon} {risk.get('risk_level', '')} (score: {risk.get('risk_score', 0):.2f})

### Primary Risk Factors
{risk_factors}

### Mitigating Factors
{mitigators}

---
*Generated by Market Research Intelligence Pipeline — Run {run_id}*
"""


# ── Entry point ───────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: python pipeline.py "<company or topic>"')
        sys.exit(1)

    query  = " ".join(sys.argv[1:])
    run_id = uuid.uuid4().hex[:12]

    result = Orchestrator(run_id=run_id).run_pipeline(query)

    if result["status"] == "rejected":
        console.print("\n[bold red]Pipeline halted — report rejected at HITL gate.[/bold red]")
        return

    # Print report
    console.print("\n" + result["report"])

    # Save report
    report_path = Path(f"report_{run_id}.md")
    report_path.write_text(result["report"])

    # Summary table
    table = Table(title="Pipeline Summary", show_header=True, header_style="bold cyan")
    table.add_column("Metric",  style="cyan",  no_wrap=True)
    table.add_column("Value",   style="white")
    table.add_row("Run ID",     run_id)
    table.add_row("Total time", f"{result['elapsed_s']:.1f} s")
    table.add_row("Total cost", f"${result['total_cost_usd']:.4f}")
    table.add_row("Report",     str(report_path))
    console.print(table)


if __name__ == "__main__":
    main()
```

### Run the pipeline

```bash
python pipeline.py "Tesla electric vehicles Q4 2024"
```

Expected terminal output (condensed):

```
╭─────────────────────────────────────────────────╮
│ Market Research Intelligence Pipeline            │
│ Query : Tesla electric vehicles Q4 2024          │
│ Run ID: a3f9d1c02b4e                             │
╰─────────────────────────────────────────────────╯

Stage 1 — Gathering intelligence
  Running news_agent...
  ✓ news_agent — 3241 ms | 892 tokens | $0.0008
  Running sentiment_agent...
  ✓ sentiment_agent — 2910 ms | 756 tokens | $0.0006
  Running financials_agent...
  ✓ financials_agent — 1874 ms | 612 tokens | $0.0005

Stage 2 — Applying skills
  ✓ executive_summary — verdict: Favorable | headline: Tesla posts record Q4 ...
  ✓ classify_risk — level: Medium | score: 0.48

# Market Intelligence Report
...

╭── Pipeline Summary ──────────────────────────────╮
│ Run ID     │ a3f9d1c02b4e                        │
│ Total time │ 12.3 s                              │
│ Total cost │ $0.0062                             │
│ Report     │ report_a3f9d1c02b4e.md              │
╰─────────────────────────────────────────────────╯
```

Try a company that tends to generate higher risk scores to trigger the HITL gate:

```bash
python pipeline.py "Archegos Capital leveraged positions"
```

---

## Part 7 — Reading the Observability Output

Every significant event in the pipeline — agent start/end, tool calls, skill invocations, HITL decisions, pipeline totals — is appended to `pipeline_runs.jsonl` as a structured JSON line.

### Inspect the raw log

```bash
# Count events by type
cat pipeline_runs.jsonl | python -c "
import sys, json, collections
types = [json.loads(l)['event_type'] for l in sys.stdin]
for k, v in collections.Counter(types).most_common():
    print(f'  {k:<30} {v}')
"
```

### Build a run summary script

Create `summarize_run.py` next to your other files:

```python
# summarize_run.py
#!/usr/bin/env python3
"""Parse pipeline_runs.jsonl and print a cost + latency report."""
import json
import sys
from collections import defaultdict
from pathlib import Path

LOG_FILE = Path("pipeline_runs.jsonl")

def main():
    if not LOG_FILE.exists():
        print("No pipeline_runs.jsonl found. Run the pipeline first.")
        return

    events = [json.loads(line) for line in LOG_FILE.read_text().splitlines() if line.strip()]

    # Group events by run_id
    runs: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        if rid := e.get("run_id"):
            runs[rid].append(e)

    print(f"\n{'RUN ID':<14} {'STATUS':<10} {'TIME(s)':<9} {'COST($)':<10} {'IN TOK':<8} {'OUT TOK':<8} {'RISK'}")
    print("-" * 72)

    for run_id, evts in runs.items():
        end = next((e for e in evts if e["event_type"] == "pipeline_end"), None)
        if not end:
            continue
        print(
            f"{run_id:<14} "
            f"{end.get('status','?'):<10} "
            f"{end.get('elapsed_ms', 0)/1000:<9.1f} "
            f"{end.get('total_cost_usd', 0):<10.4f} "
            f"{end.get('total_input_tokens', 0):<8} "
            f"{end.get('total_output_tokens', 0):<8} "
            f"{end.get('risk_score', '?')}"
        )

    # Per-agent latency for the most recent run
    latest_run_id = list(runs.keys())[-1]
    print(f"\nPer-agent breakdown for run {latest_run_id}:")
    print(f"  {'AGENT':<22} {'ELAPSED(ms)':<14} {'INPUT':<8} {'OUTPUT':<8} {'COST($)'}")
    print("  " + "-" * 60)
    for e in runs[latest_run_id]:
        if e["event_type"] == "agent_end":
            print(
                f"  {e['agent']:<22} "
                f"{e.get('elapsed_ms', 0):<14.0f} "
                f"{e.get('input_tokens', 0):<8} "
                f"{e.get('output_tokens', 0):<8} "
                f"{e.get('cost_usd', 0):.4f}"
            )


if __name__ == "__main__":
    main()
```

Run it:

```bash
python summarize_run.py
```

Example output:

```
RUN ID         STATUS     TIME(s)  COST($)    IN TOK  OUT TOK  RISK
------------------------------------------------------------------------
a3f9d1c02b4e  delivered  12.3     0.0062     2847    1204     0.48
b7e2a4f91c30  rejected   9.1      0.0055     2341    987      0.83

Per-agent breakdown for run a3f9d1c02b4e:
  AGENT                  ELAPSED(ms)   INPUT   OUTPUT  COST($)
  ------------------------------------------------------------
  news_agent             3241          512     380     0.0008
  sentiment_agent        2910          423     333     0.0006
  financials_agent       1874          341     271     0.0005
```

---

## Challenges

Work through these after completing the main pipeline. Each builds directly on the code you wrote.

---

### Challenge A — Add a Fourth Worker Agent (Easy)

Add a `CompetitorAgent` to `agents.py` that uses the `search_news` tool to research the top two competitors of the queried company and returns a JSON object:

```json
{
  "competitors": [
    {"name": "...", "competitive_position": "...", "key_differentiator": "..."},
    {"name": "...", "competitive_position": "...", "key_differentiator": "..."}
  ],
  "competitive_threat": "low" | "medium" | "high"
}
```

Wire it into the orchestrator between `financials_result` and the aggregation step. Include its output in `research_data`.

**Hint:** The agent class needs only `name`, `system_prompt`, and `allowed_tools`. The orchestrator call is one line.

---

### Challenge B — Run Workers in Parallel (Medium)

The three worker agents currently run **sequentially** (each waits for the previous one to finish). They are completely independent — perfect candidates for parallelization.

Replace the sequential calls in `Orchestrator.run_pipeline()` with `concurrent.futures.ThreadPoolExecutor`:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

with ThreadPoolExecutor(max_workers=3) as executor:
    futures = {
        executor.submit(self._run_agent, NewsAgent,       query,           orch_span.span_id): "news",
        executor.submit(self._run_agent, SentimentAgent,  f"...: {query}", orch_span.span_id): "sentiment",
        executor.submit(self._run_agent, FinancialsAgent, f"...: {query}", orch_span.span_id): "financials",
    }
    results = {}
    for future in as_completed(futures):
        key = futures[future]
        results[key] = future.result()
```

Measure the wall-clock improvement by comparing `elapsed_s` from `pipeline_runs.jsonl` before and after.

**Expected improvement:** ~2.5–3× faster (limited by the slowest agent rather than the sum).

---

### Challenge C — Add Prompt Caching to Workers (Hard)

The `system_prompt` on each worker is a static string that never changes between runs — it's an ideal candidate for [Anthropic prompt caching](../../concepts/07-observability.md).

Modify `AgentWorker.run()` to pass the system prompt as a `cache_control` block:

```python
response = client.messages.create(
    model=MODEL,
    max_tokens=2048,
    system=[
        {
            "type": "text",
            "text": self.system_prompt,
            "cache_control": {"type": "ephemeral"},
        }
    ],
    ...
)
```

Then update `TokenUsage` to capture `response.usage.cache_read_input_tokens` and `response.usage.cache_creation_input_tokens`. Run the same query twice and compare:

- First run: `cache_write_tokens > 0`, `cache_read_tokens == 0`
- Second run: `cache_write_tokens == 0`, `cache_read_tokens > 0`

Update `summarize_run.py` to show cache hit rate per agent: `cache_read / (cache_read + input_tokens)`.

---

### Challenge D — LLM-as-Judge Eval Loop (Expert)

Add a fifth skill `evaluate_report_quality` to `skills.py` that takes the final markdown report as input and returns a quality score:

```json
{
  "score": 0.0–1.0,
  "dimensions": {
    "specificity": 0.0–1.0,
    "actionability": 0.0–1.0,
    "risk_coverage": 0.0–1.0
  },
  "improvement_suggestions": ["...", "..."]
}
```

Then add an eval loop to `pipeline.py`: after delivering the report, invoke `evaluate_report_quality`. If `score < 0.65`, feed the suggestions back to the orchestrator as a revision request and generate a second report. Log both attempts in `pipeline_runs.jsonl` with a `report_version` field (1 and 2).

This is the foundation of the **Critic-Revise** pattern described in [concepts/03-subagents-orchestration.md](../../concepts/03-subagents-orchestration.md).

---

## Reference

| Pattern | File | Key function/class |
|---|---|---|
| Structured log writer | `observability.py` | `write_log_event()` |
| Span tracking | `observability.py` | `SpanContext`, `PipelineTracer.span()` |
| Tool schema format | `tools.py` | `TOOLS` list |
| Tool dispatcher | `tools.py` | `execute_tool()` |
| Agentic loop | `agents.py` | `AgentWorker.run()` |
| Worker isolation | `agents.py` | `NewsAgent`, `SentimentAgent`, `FinancialsAgent` |
| Skill registry | `skills.py` | `SKILL_REGISTRY`, `invoke_skill()` |
| HITL gate | `hitl.py` | `hitl_gate()` |
| Orchestrator | `pipeline.py` | `Orchestrator.run_pipeline()` |
| Report assembly | `pipeline.py` | `_assemble_report()` |

Concept files to read alongside this exercise:

- [concepts/02-agent-architecture.md](../../concepts/02-agent-architecture.md)
- [concepts/03-subagents-orchestration.md](../../concepts/03-subagents-orchestration.md)
- [concepts/04-skills.md](../../concepts/04-skills.md)
- [concepts/05-enterprise-patterns.md](../../concepts/05-enterprise-patterns.md)
- [concepts/07-observability.md](../../concepts/07-observability.md)
