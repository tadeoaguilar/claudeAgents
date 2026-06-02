"""
Exercise 05 — Observability

Instruments the research agent with structured logging and cost tracking.
Every event is written to agent_runs.jsonl as a JSON line.

Run:
    python monitored_agent.py
    python summarise_logs.py   # after running monitored_agent.py
"""

import json
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv
import anthropic
from rich.console import Console
from rich.panel import Panel

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
console = Console()

LOG_FILE = "agent_runs.jsonl"

# ──────────────────────────────────────────────
# 1. Structured log emitter
# ──────────────────────────────────────────────

def emit(event_type: str, data: dict) -> None:
    record = {
        "event": event_type,
        "timestamp": time.time(),
        **data,
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")


# ──────────────────────────────────────────────
# 2. Cost calculator
# ──────────────────────────────────────────────

PRICING = {
    "claude-opus-4-8":          {"input": 15.00, "output": 75.00, "cache_write": 18.75, "cache_read": 1.50},
    "claude-sonnet-4-6":        {"input":  3.00, "output": 15.00, "cache_write":  3.75, "cache_read": 0.30},
    "claude-haiku-4-5-20251001":{"input":  0.80, "output":  4.00, "cache_write":  1.00, "cache_read": 0.08},
}

def compute_cost(model: str, usage) -> float:
    p = PRICING.get(model, PRICING["claude-opus-4-8"])
    return (
        getattr(usage, "input_tokens", 0)                  * p["input"]        / 1_000_000 +
        getattr(usage, "output_tokens", 0)                 * p["output"]       / 1_000_000 +
        getattr(usage, "cache_creation_input_tokens", 0)   * p["cache_write"]  / 1_000_000 +
        getattr(usage, "cache_read_input_tokens", 0)       * p["cache_read"]   / 1_000_000
    )


# ──────────────────────────────────────────────
# 3. Mock tools (same as Exercise 02)
# ──────────────────────────────────────────────

MOCK_DATABASE = {
    "stripe": {
        "profile":    {"name": "Stripe", "industry": "Fintech", "founded": 2010, "hq": "San Francisco"},
        "financials": {"revenue_usd_b": 14.4, "yoy_growth_pct": 25, "employees": 8000},
        "news":       [{"date": "2025-05-20", "headline": "Stripe launches AI fraud detection"}],
    },
}

def search_company_database(company: str) -> str:
    time.sleep(0.05)  # Simulate latency
    data = MOCK_DATABASE.get(company.lower())
    return json.dumps(data["profile"] if data else {"error": "not found"})

def get_financial_metrics(company: str) -> str:
    time.sleep(0.08)
    data = MOCK_DATABASE.get(company.lower())
    return json.dumps(data["financials"] if data else {"error": "not found"})

def get_recent_news(company: str) -> str:
    time.sleep(0.03)
    data = MOCK_DATABASE.get(company.lower())
    return json.dumps(data["news"] if data else {"error": "not found"})

TOOL_REGISTRY = {
    "search_company_database": search_company_database,
    "get_financial_metrics":   get_financial_metrics,
    "get_recent_news":         get_recent_news,
}

TOOLS = [
    {
        "name": "search_company_database",
        "description": "Look up a company's basic profile.",
        "input_schema": {"type": "object", "properties": {"company": {"type": "string"}}, "required": ["company"]}
    },
    {
        "name": "get_financial_metrics",
        "description": "Get revenue, growth, employee count for a company.",
        "input_schema": {"type": "object", "properties": {"company": {"type": "string"}}, "required": ["company"]}
    },
    {
        "name": "get_recent_news",
        "description": "Get recent news headlines for a company.",
        "input_schema": {"type": "object", "properties": {"company": {"type": "string"}}, "required": ["company"]}
    },
]

SYSTEM_PROMPT = """You are a company research analyst. When given a company name:
1. Call all three tools simultaneously to gather profile, financials, and news
2. Return a JSON report: {"company": str, "summary": str, "profile": {}, "financials": {}, "news": []}
Return only the JSON object.
"""

MODEL = "claude-haiku-4-5-20251001"


# ──────────────────────────────────────────────
# 4. Instrumented agent loop
# ──────────────────────────────────────────────

def run_monitored_agent(company: str, tenant_id: str = "default") -> dict:
    run_id = str(uuid.uuid4())[:8]
    run_start = time.time()

    # Aggregated metrics across all turns in this run
    total_input_tokens       = 0
    total_output_tokens      = 0
    total_cache_read_tokens  = 0
    total_cache_write_tokens = 0
    total_cost_usd           = 0.0
    total_tool_calls         = 0
    turn_count               = 0

    emit("run_start", {
        "run_id": run_id,
        "company": company,
        "tenant_id": tenant_id,
        "model": MODEL,
    })

    messages = [{"role": "user", "content": f"Research {company} and produce the structured report."}]

    for iteration in range(1, 10):
        turn_start = time.time()
        turn_count += 1

        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            tools=TOOLS,
            messages=messages,
        )

        turn_cost = compute_cost(MODEL, response.usage)
        turn_duration_ms = (time.time() - turn_start) * 1000

        # Accumulate
        total_input_tokens       += response.usage.input_tokens
        total_output_tokens      += response.usage.output_tokens
        total_cache_read_tokens  += getattr(response.usage, "cache_read_input_tokens", 0)
        total_cache_write_tokens += getattr(response.usage, "cache_creation_input_tokens", 0)
        total_cost_usd           += turn_cost

        emit("model_call", {
            "run_id": run_id,
            "turn": turn_count,
            "model": MODEL,
            "input_tokens":       response.usage.input_tokens,
            "output_tokens":      response.usage.output_tokens,
            "cache_read_tokens":  getattr(response.usage, "cache_read_input_tokens", 0),
            "cache_write_tokens": getattr(response.usage, "cache_creation_input_tokens", 0),
            "cost_usd":           round(turn_cost, 6),
            "duration_ms":        round(turn_duration_ms, 1),
            "stop_reason":        response.stop_reason,
        })

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            raw = next((b.text for b in response.content if hasattr(b, "text")), "{}")
            try:
                result = json.loads(raw)
                status = "success"
            except json.JSONDecodeError:
                result = {"error": "non_json_output"}
                status = "failure"

            run_duration_ms = (time.time() - run_start) * 1000

            emit("run_complete", {
                "run_id":               run_id,
                "company":              company,
                "tenant_id":            tenant_id,
                "status":               status,
                "turn_count":           turn_count,
                "total_tool_calls":     total_tool_calls,
                "total_input_tokens":   total_input_tokens,
                "total_output_tokens":  total_output_tokens,
                "cache_read_tokens":    total_cache_read_tokens,
                "cache_write_tokens":   total_cache_write_tokens,
                "total_cost_usd":       round(total_cost_usd, 6),
                "duration_ms":          round(run_duration_ms, 1),
            })

            console.print(
                f"[green]Run {run_id}[/green] | {status} | "
                f"{turn_count} turns | {total_tool_calls} tools | "
                f"${total_cost_usd:.4f} | {run_duration_ms:.0f}ms"
            )
            return result

        if response.stop_reason == "tool_use":
            tool_blocks = [b for b in response.content if b.type == "tool_use"]

            # Execute tools in parallel
            tool_results = []
            with ThreadPoolExecutor(max_workers=len(tool_blocks)) as executor:
                futures = {}
                for block in tool_blocks:
                    fn = TOOL_REGISTRY.get(block.name)
                    tool_start = time.time()
                    if fn:
                        future = executor.submit(fn, **block.input)
                    else:
                        future = executor.submit(lambda: json.dumps({"error": "tool not found"}))
                    futures[future] = (block, tool_start)

                for future in as_completed(futures):
                    block, t_start = futures[future]
                    try:
                        result = future.result()
                        error = None
                    except Exception as e:
                        result = json.dumps({"error": str(e)})
                        error = str(e)

                    t_duration_ms = (time.time() - t_start) * 1000
                    total_tool_calls += 1

                    emit("tool_call", {
                        "run_id":      run_id,
                        "turn":        turn_count,
                        "tool":        block.name,
                        "input":       block.input,
                        "output_len":  len(result),
                        "duration_ms": round(t_duration_ms, 1),
                        "error":       error,
                    })

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            messages.append({"role": "user", "content": tool_results})

    emit("run_complete", {
        "run_id": run_id, "company": company, "status": "max_iterations",
        "turn_count": turn_count, "total_cost_usd": round(total_cost_usd, 6),
    })
    return {"error": "max_iterations_reached"}


# ──────────────────────────────────────────────
# 5. Main
# ──────────────────────────────────────────────

if __name__ == "__main__":
    console.print(f"Logging to: [bold]{LOG_FILE}[/bold]\n")

    # Run the agent 3 times (to see caching effects)
    for i in range(3):
        console.print(f"\n[bold]── Run {i+1} ──[/bold]")
        run_monitored_agent("Stripe", tenant_id="acme-corp")

    console.print(f"\n[green]✓ Done. Run 'python summarise_logs.py' to see the report.[/green]")
