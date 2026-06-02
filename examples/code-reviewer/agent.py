"""
Example: Code Review Agent

Reviews a git diff for bugs, security issues, and style violations.
Returns structured inline comments similar to a GitHub PR review.

Run:
    python agent.py
"""

import json
import os
import subprocess
from dataclasses import dataclass

from dotenv import load_dotenv
import anthropic
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.syntax import Syntax

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
console = Console()

# ── Mock diff (simulates a real PR diff) ────────────────────────

SAMPLE_DIFF = """
diff --git a/api/auth.py b/api/auth.py
index abc1234..def5678 100644
--- a/api/auth.py
+++ b/api/auth.py
@@ -12,8 +12,20 @@ from models import User

 def login(username: str, password: str) -> dict:
-    user = User.query.filter_by(username=username).first()
+    user = User.query.filter_by(username=username, password=password).first()
     if not user:
         return {"error": "Invalid credentials"}
-    if not check_password_hash(user.password_hash, password):
-        return {"error": "Invalid credentials"}
+    token = jwt.encode({"user_id": user.id, "exp": datetime.utcnow() + timedelta(days=365)},
+                       "secret123",
+                       algorithm="HS256")
     return {"token": token}
+
+def get_user_data(user_id: str) -> dict:
+    sql = f"SELECT * FROM users WHERE id = {user_id}"
+    result = db.execute(sql)
+    return result.fetchone()
"""

# ── Tool implementations ────────────────────────────────────────

def get_diff(source: str = "sample") -> str:
    if source == "sample":
        return SAMPLE_DIFF
    if source == "git":
        try:
            result = subprocess.run(
                ["git", "diff", "HEAD~1"],
                capture_output=True, text=True, timeout=10
            )
            return result.stdout if result.stdout else "No diff found"
        except subprocess.TimeoutExpired:
            return json.dumps({"error": "git diff timed out"})
    return json.dumps({"error": f"Unknown source '{source}'"})

def lookup_security_rule(rule_id: str) -> str:
    rules = {
        "SQL-INJ": "SQL injection: User-controlled input concatenated directly into SQL. Fix: use parameterised queries.",
        "HARDCODED-SECRET": "Hardcoded secret: Secret value embedded in source code. Fix: use environment variables.",
        "WEAK-HASH": "Weak password hashing: Passwords compared as plaintext or with weak hash. Fix: use bcrypt/argon2.",
        "LONG-JWT-EXP": "Long JWT expiry: Token valid for >24h increases breach window. Fix: use short-lived tokens + refresh.",
    }
    return json.dumps(rules.get(rule_id, {"error": f"Rule '{rule_id}' not found"}))

TOOL_REGISTRY = {
    "get_diff": get_diff,
    "lookup_security_rule": lookup_security_rule,
}

TOOLS = [
    {
        "name": "get_diff",
        "description": "Get the code diff to review. Use source='sample' for the built-in example.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "enum": ["sample", "git"], "description": "Where to get the diff"}
            },
            "required": ["source"]
        }
    },
    {
        "name": "lookup_security_rule",
        "description": "Look up details about a security rule by ID. Use when you detect a potential security issue.",
        "input_schema": {
            "type": "object",
            "properties": {
                "rule_id": {
                    "type": "string",
                    "enum": ["SQL-INJ", "HARDCODED-SECRET", "WEAK-HASH", "LONG-JWT-EXP"],
                    "description": "The security rule ID"
                }
            },
            "required": ["rule_id"]
        }
    },
]

SYSTEM_PROMPT = """You are a senior software engineer performing a code review.

Review the diff for:
1. Security vulnerabilities (SQL injection, hardcoded secrets, auth bypasses, weak crypto)
2. Correctness bugs (logic errors, off-by-one, null handling, race conditions)
3. Code quality (readability, naming, duplication, unnecessary complexity)

For each issue found:
- Look up any security rules using lookup_security_rule
- Provide a specific, actionable comment

Return ONLY this JSON:
{
  "verdict": "approve" | "request_changes" | "comment",
  "summary": string (1-2 sentences: overall assessment),
  "comments": [
    {
      "file": string,
      "line_hint": string (e.g. "+    sql = f\"SELECT...\""),
      "severity": "critical" | "high" | "medium" | "low" | "info",
      "category": "security" | "bug" | "style" | "performance",
      "message": string (what is wrong),
      "suggestion": string (how to fix it)
    }
  ],
  "security_score": int (0-10, 10 = no issues),
  "must_fix_before_merge": [string] (short list of blocking issues)
}
"""

def run_code_review(pr_description: str = "") -> dict:
    console.print(Panel(
        f"[cyan]PR:[/cyan] {pr_description or 'Code review request'}",
        title="Code Review Agent"
    ))

    messages = [{
        "role": "user",
        "content": f"Review this pull request.\n\nDescription: {pr_description or 'N/A'}\n\n"
                   "Get the diff and produce a structured code review."
    }]

    for _ in range(10):
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            tools=TOOLS,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            raw = next((b.text for b in response.content if hasattr(b, "text")), "{}")
            try:
                review = json.loads(raw)
            except json.JSONDecodeError:
                review = {"error": "parse_failed"}

            # Render the review
            verdict = review.get("verdict", "?")
            verdict_colors = {"approve": "green", "request_changes": "red", "comment": "yellow"}
            color = verdict_colors.get(verdict, "white")

            console.print(Panel(
                f"[{color}][bold]{verdict.upper().replace('_', ' ')}[/bold][/{color}]\n\n"
                f"{review.get('summary', '')}\n\n"
                f"Security score: {review.get('security_score', '?')}/10",
                title="Review Verdict"
            ))

            comments = review.get("comments", [])
            if comments:
                table = Table(title="Review Comments")
                table.add_column("Sev", style="bold", width=8)
                table.add_column("Category", width=10)
                table.add_column("Issue")
                table.add_column("Fix")

                sev_colors = {"critical": "red", "high": "red", "medium": "yellow", "low": "blue", "info": "dim"}
                for c in comments:
                    sev = c.get("severity", "info")
                    table.add_row(
                        f"[{sev_colors.get(sev, 'white')}]{sev}[/{sev_colors.get(sev, 'white')}]",
                        c.get("category", "?"),
                        c.get("message", ""),
                        c.get("suggestion", ""),
                    )
                console.print(table)

            must_fix = review.get("must_fix_before_merge", [])
            if must_fix:
                console.print("\n[red bold]Must fix before merge:[/red bold]")
                for item in must_fix:
                    console.print(f"  [red]✗[/red] {item}")

            return review

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    console.print(f"  [yellow]→[/yellow] {block.name}({block.input})")
                    fn = TOOL_REGISTRY.get(block.name)
                    result = fn(**block.input) if fn else json.dumps({"error": "not found"})
                    tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result})
            messages.append({"role": "user", "content": tool_results})

    return {"error": "max_iterations"}


if __name__ == "__main__":
    run_code_review("Fix authentication: simplify login flow and add user data endpoint")
