"""
Example: Data Analyst Agent

Answers business questions by querying a SQLite database, computing statistics,
and generating a structured report with narrative.

Run:
    python agent.py
"""

import json
import os
import sqlite3
import time
from pathlib import Path

from dotenv import load_dotenv
import anthropic
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
console = Console()

DB_PATH = Path(__file__).parent / "sales.db"

# ── Seed the database ───────────────────────────────────────────

def seed_database():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.executescript("""
        DROP TABLE IF EXISTS sales;
        CREATE TABLE sales (
            id INTEGER PRIMARY KEY,
            date TEXT,
            region TEXT,
            product TEXT,
            revenue REAL,
            units INTEGER
        );
        INSERT INTO sales VALUES
            (1,'2025-01-15','AMER','Pro Plan',12000,24),
            (2,'2025-01-22','EMEA','Starter',  3500,35),
            (3,'2025-02-10','APAC','Pro Plan',  8000,16),
            (4,'2025-02-18','AMER','Enterprise',25000,5),
            (5,'2025-03-05','EMEA','Pro Plan',  9500,19),
            (6,'2025-03-12','APAC','Starter',   2000,20),
            (7,'2025-04-01','AMER','Pro Plan',  14000,28),
            (8,'2025-04-15','EMEA','Enterprise',22000,4),
            (9,'2025-05-20','AMER','Starter',   4000,40),
            (10,'2025-05-28','APAC','Enterprise',18000,3);
    """)
    conn.commit()
    conn.close()

# ── Tool implementations ────────────────────────────────────────

def query_database(sql: str) -> str:
    sql_upper = sql.strip().upper()
    if not sql_upper.startswith("SELECT"):
        return json.dumps({"error": "Only SELECT statements are allowed"})

    allowed_keywords = {"SELECT", "FROM", "WHERE", "GROUP", "BY", "ORDER", "LIMIT",
                        "HAVING", "JOIN", "AS", "SUM", "AVG", "COUNT", "MAX", "MIN", "ROUND"}
    words = set(sql_upper.split())
    dangerous = words - allowed_keywords - {"AND", "OR", "ON", "IN", "NOT", "NULL",
                                             "BETWEEN", "LIKE", "DESC", "ASC", "DISTINCT"}
    if any(kw in dangerous for kw in ["DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "CREATE"]):
        return json.dumps({"error": "Dangerous statement detected"})

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(sql)
        rows = [dict(row) for row in cur.fetchall()]
        conn.close()
        return json.dumps(rows)
    except sqlite3.Error as e:
        return json.dumps({"error": str(e)})

def get_schema() -> str:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT sql FROM sqlite_master WHERE type='table'")
    schema = [row[0] for row in cur.fetchall()]
    conn.close()
    return json.dumps({"tables": schema})

TOOL_REGISTRY = {
    "query_database": query_database,
    "get_schema": get_schema,
}

TOOLS = [
    {
        "name": "get_schema",
        "description": "Get the database schema (table names and column definitions).",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "query_database",
        "description": "Run a read-only SQL SELECT query against the sales database. Returns rows as JSON.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "A valid SELECT statement"}
            },
            "required": ["sql"]
        }
    },
]

SYSTEM_PROMPT = """You are a business intelligence analyst. Answer the user's question by:

1. Calling get_schema to understand the data structure
2. Writing and executing appropriate SQL queries
3. Interpreting the results

Return a JSON report:
{
  "question": string,
  "answer": string (direct answer, 1-2 sentences),
  "key_findings": [string],
  "data": any (the raw query results or computed summary),
  "methodology": string (which SQL queries you ran and why)
}

Always:
- Validate your SQL logic before executing
- Round monetary values to 2 decimal places
- Flag if data seems incomplete or unexpected

Return ONLY the JSON. No markdown, no preamble.
"""

def run_analyst(question: str) -> dict:
    console.print(Panel(f"[cyan]Q:[/cyan] {question}", title="Data Analyst"))
    messages = [{"role": "user", "content": question}]

    for _ in range(10):
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            tools=TOOLS,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            raw = next((b.text for b in response.content if hasattr(b, "text")), "{}")
            try:
                result = json.loads(raw)
            except json.JSONDecodeError:
                result = {"error": "parse_failed"}

            console.print(Panel(
                f"[bold]Answer:[/bold] {result.get('answer', '?')}\n\n"
                + "\n".join(f"• {f}" for f in result.get("key_findings", [])),
                title="[green]Analysis Result[/green]"
            ))
            return result

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    console.print(f"  [yellow]SQL:[/yellow] {block.input.get('sql', '')[:80]}")
                    fn = TOOL_REGISTRY.get(block.name)
                    result = fn(**block.input) if fn else json.dumps({"error": "not found"})
                    tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result})
            messages.append({"role": "user", "content": tool_results})

    return {"error": "max_iterations"}


if __name__ == "__main__":
    seed_database()
    console.print("[dim]Database seeded.[/dim]\n")

    questions = [
        "What is the total revenue by region in 2025?",
        "Which product line has the highest average deal size?",
        "Show me the month-over-month revenue trend for 2025.",
    ]

    for q in questions:
        run_analyst(q)
        console.print("\n" + "─" * 60 + "\n")
