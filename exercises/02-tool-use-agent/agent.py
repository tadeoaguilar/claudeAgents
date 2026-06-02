"""
Exercise 02 — Tool-Use Agent

A company research agent that uses three tools to answer questions about companies.
Demonstrates: multiple tools, parallel tool calls, structured JSON output.

Run:
    python agent.py
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
import anthropic
from rich.console import Console
from rich.json import JSON
from rich.panel import Panel
from rich.table import Table

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
console = Console()

# ──────────────────────────────────────────────
# 1. Mock data store
# ──────────────────────────────────────────────

MOCK_DATABASE = {
    "stripe": {
        "profile": {
            "name": "Stripe",
            "industry": "Fintech / Payment Processing",
            "founded": 2010,
            "headquarters": "San Francisco, CA",
            "ceo": "Patrick Collison",
            "website": "stripe.com",
        },
        "financials": {
            "revenue_usd_billions": 14.4,
            "yoy_growth_pct": 25,
            "employee_count": 8000,
            "last_valuation_usd_billions": 50,
        },
        "news": [
            {"date": "2025-05-20", "headline": "Stripe launches AI-powered fraud detection suite"},
            {"date": "2025-04-15", "headline": "Stripe processes $1 trillion in annual payment volume"},
            {"date": "2025-03-10", "headline": "Stripe expands to 10 new markets in Africa and Southeast Asia"},
        ],
    },
    "shopify": {
        "profile": {
            "name": "Shopify",
            "industry": "E-commerce Platform / SaaS",
            "founded": 2006,
            "headquarters": "Ottawa, Canada",
            "ceo": "Tobias Lütke",
            "website": "shopify.com",
        },
        "financials": {
            "revenue_usd_billions": 7.1,
            "yoy_growth_pct": 21,
            "employee_count": 11600,
            "last_valuation_usd_billions": 95,
        },
        "news": [
            {"date": "2025-05-18", "headline": "Shopify announces AI shopping assistant across all merchant stores"},
            {"date": "2025-04-02", "headline": "Shopify partners with major banks to offer merchant capital products"},
            {"date": "2025-02-28", "headline": "Shopify Q4 2024 GMV reaches $75 billion"},
        ],
    },
}

# ──────────────────────────────────────────────
# 2. Tool implementations
# ──────────────────────────────────────────────

def search_company_database(company: str) -> str:
    """Return basic profile data for a company."""
    key = company.lower().strip()
    data = MOCK_DATABASE.get(key)
    if not data:
        return json.dumps({"error": f"Company '{company}' not found in database"})
    return json.dumps(data["profile"])


def get_financial_metrics(company: str) -> str:
    """Return financial metrics for a company."""
    key = company.lower().strip()
    data = MOCK_DATABASE.get(key)
    if not data:
        return json.dumps({"error": f"No financial data for '{company}'"})
    return json.dumps(data["financials"])


def get_recent_news(company: str) -> str:
    """Return the three most recent news items about a company."""
    key = company.lower().strip()
    data = MOCK_DATABASE.get(key)
    if not data:
        return json.dumps({"error": f"No news found for '{company}'"})
    return json.dumps(data["news"])


TOOL_REGISTRY = {
    "search_company_database": search_company_database,
    "get_financial_metrics":   get_financial_metrics,
    "get_recent_news":         get_recent_news,
}

# ──────────────────────────────────────────────
# 3. Tool schemas
# ──────────────────────────────────────────────

COMPANY_PARAM = {
    "company": {
        "type": "string",
        "description": "The company name (e.g. 'Stripe', 'Shopify')"
    }
}

TOOLS = [
    {
        "name": "search_company_database",
        "description": "Look up a company's basic profile: name, industry, founding year, HQ, CEO, website.",
        "input_schema": {
            "type": "object",
            "properties": COMPANY_PARAM,
            "required": ["company"]
        }
    },
    {
        "name": "get_financial_metrics",
        "description": "Retrieve financial data for a company: revenue, YoY growth, employee count, valuation.",
        "input_schema": {
            "type": "object",
            "properties": COMPANY_PARAM,
            "required": ["company"]
        }
    },
    {
        "name": "get_recent_news",
        "description": "Get the three most recent news headlines and dates for a company.",
        "input_schema": {
            "type": "object",
            "properties": COMPANY_PARAM,
            "required": ["company"]
        }
    },
]

# ──────────────────────────────────────────────
# 4. System prompt
# ──────────────────────────────────────────────

SYSTEM_PROMPT = """You are an enterprise research analyst. When given a company name, you must:

1. Call ALL THREE tools simultaneously to gather complete information:
   - search_company_database (profile)
   - get_financial_metrics (financials)
   - get_recent_news (latest news)

2. Synthesise the results into a structured JSON report with exactly this schema:
{
  "company_name": string,
  "summary": string (2-3 sentences),
  "profile": { "industry": string, "founded": int, "hq": string, "ceo": string },
  "financials": {
    "revenue_usd_b": float,
    "yoy_growth_pct": int,
    "employees": int,
    "valuation_usd_b": float
  },
  "recent_developments": [ { "date": string, "headline": string } ],
  "analyst_note": string (1-2 sentences with your assessment)
}

Return ONLY the JSON object — no preamble, no explanation, no markdown fences.
"""

# ──────────────────────────────────────────────
# 5. Tool execution (with parallel support)
# ──────────────────────────────────────────────

def execute_tools_parallel(tool_use_blocks: list) -> list[dict]:
    """
    Execute multiple tool calls concurrently.
    Returns a list of tool_result dicts ready to append to messages.
    """
    results = {}

    def run_one(block):
        tool_fn = TOOL_REGISTRY.get(block.name)
        if tool_fn is None:
            return block.id, f"Error: tool '{block.name}' not found"
        try:
            return block.id, tool_fn(**block.input)
        except Exception as e:
            return block.id, f"Error executing '{block.name}': {e}"

    with ThreadPoolExecutor(max_workers=len(tool_use_blocks)) as executor:
        futures = {executor.submit(run_one, block): block for block in tool_use_blocks}
        for future in as_completed(futures):
            tool_id, result = future.result()
            results[tool_id] = result

    # Build tool_result list preserving original order
    return [
        {
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": results[block.id],
        }
        for block in tool_use_blocks
    ]

# ──────────────────────────────────────────────
# 6. Agent loop
# ──────────────────────────────────────────────

def run_research_agent(company: str) -> dict:
    console.print(Panel(f"[bold cyan]Researching:[/bold cyan] {company}", title="Research Agent"))

    messages = [{"role": "user", "content": f"Research {company} and produce the structured report."}]

    for iteration in range(1, 8):
        console.print(f"\n[dim]── Turn {iteration} ──[/dim]")

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"}
            }],
            tools=TOOLS,
            messages=messages,
        )

        console.print(
            f"  [dim]Tokens: {response.usage.input_tokens} in / "
            f"{response.usage.output_tokens} out | stop: {response.stop_reason}[/dim]"
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            raw = next(
                (block.text for block in response.content if hasattr(block, "text")),
                "{}"
            )
            try:
                report = json.loads(raw)
                console.print(Panel(JSON(json.dumps(report, indent=2)), title="[green]Research Report[/green]"))
                return report
            except json.JSONDecodeError:
                console.print(f"[red]Could not parse JSON output:[/red] {raw[:200]}")
                return {"error": "output_not_json", "raw": raw}

        if response.stop_reason == "tool_use":
            tool_blocks = [b for b in response.content if b.type == "tool_use"]

            # Show what Claude is about to call
            table = Table(show_header=True)
            table.add_column("Tool", style="yellow")
            table.add_column("Input")
            for b in tool_blocks:
                table.add_row(b.name, json.dumps(b.input))
            console.print(table)

            # Execute in parallel
            tool_results = execute_tools_parallel(tool_blocks)
            messages.append({"role": "user", "content": tool_results})

    return {"error": "max_iterations_reached"}


# ──────────────────────────────────────────────
# 7. Main
# ──────────────────────────────────────────────

if __name__ == "__main__":
    for company in ["Stripe", "Shopify"]:
        run_research_agent(company)
        console.print("\n" + "─" * 60 + "\n")
