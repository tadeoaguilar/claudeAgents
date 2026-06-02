"""
Exercise 03 — Multi-Agent Pipeline

Orchestrator + two specialised subagents for customer feedback analysis.

Architecture:
    Orchestrator
      ├── SentimentAgent  (tone + themes)
      └── ActionAgent     (action items + priority)

Run:
    python pipeline.py
"""

import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv
import anthropic
from rich.console import Console
from rich.json import JSON
from rich.panel import Panel
from rich.tree import Tree

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
console = Console()

# ──────────────────────────────────────────────
# 1. Base agent runner
# ──────────────────────────────────────────────

@dataclass
class AgentWorker:
    """A self-contained subagent with its own system prompt and tools."""
    name: str
    system_prompt: str
    tools: list[dict]
    tool_implementations: dict
    model: str = "claude-haiku-4-5-20251001"
    max_iterations: int = 6

    def run(self, task: str, run_id: str | None = None) -> str:
        """Run the worker on a task and return a result string."""
        start = time.time()
        messages = [{"role": "user", "content": task}]

        console.print(f"  [cyan]Worker '{self.name}'[/cyan] started | run_id={run_id}")

        for i in range(self.max_iterations):
            response = client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=[{
                    "type": "text",
                    "text": self.system_prompt,
                    "cache_control": {"type": "ephemeral"}
                }],
                tools=self.tools if self.tools else anthropic.NOT_GIVEN,
                messages=messages,
            )

            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                result = next(
                    (block.text for block in response.content if hasattr(block, "text")),
                    "{}"
                )
                elapsed = (time.time() - start) * 1000
                console.print(
                    f"  [cyan]Worker '{self.name}'[/cyan] done in {elapsed:.0f}ms "
                    f"({response.usage.input_tokens}in/{response.usage.output_tokens}out tokens)"
                )
                return result

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        fn = self.tool_implementations.get(block.name)
                        result = fn(**block.input) if fn else f"Error: tool '{block.name}' not found"
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": str(result),
                        })
                messages.append({"role": "user", "content": tool_results})

        return json.dumps({"error": "max_iterations_reached", "worker": self.name})


# ──────────────────────────────────────────────
# 2. Specialised workers
# ──────────────────────────────────────────────

SENTIMENT_WORKER = AgentWorker(
    name="SentimentAgent",
    system_prompt="""You are a sentiment analysis specialist.

Given customer feedback text, analyse and return ONLY a JSON object:
{
  "overall_sentiment": "positive" | "neutral" | "negative" | "mixed",
  "sentiment_score": float (-1.0 to 1.0),
  "key_themes": [string],
  "emotional_signals": [string],
  "customer_intent": "retain" | "churn_risk" | "upsell_opportunity" | "support_needed"
}

Be precise. Do not include any text outside the JSON object.
""",
    tools=[],
    tool_implementations={},
)

ACTION_WORKER = AgentWorker(
    name="ActionAgent",
    system_prompt="""You are a customer success operations specialist.

Given customer feedback text, extract actionable insights and return ONLY a JSON object:
{
  "action_items": [
    {
      "action": string,
      "owner": "product" | "support" | "sales" | "engineering",
      "priority": "high" | "medium" | "low",
      "rationale": string
    }
  ],
  "follow_up_required": boolean,
  "escalation_needed": boolean,
  "escalation_reason": string | null
}

Focus on specific, concrete actions. Do not include text outside the JSON object.
""",
    tools=[],
    tool_implementations={},
)


# ──────────────────────────────────────────────
# 3. Orchestrator
# ──────────────────────────────────────────────

ORCHESTRATOR_SYSTEM = """You are a pipeline orchestrator for customer feedback analysis.

You have access to two specialised workers via the spawn_worker tool:
- "sentiment": analyses tone, themes, and customer intent
- "action": extracts action items, priorities, and escalation signals

For each piece of customer feedback:
1. Call BOTH workers simultaneously by making two spawn_worker calls in one turn
2. Wait for both results
3. Merge the results into a final structured report with this schema:

{
  "feedback_id": string,
  "analysis": {
    "sentiment": { ... from sentiment worker ... },
    "actions":   { ... from action worker ... }
  },
  "executive_summary": string (2-3 sentences for a manager),
  "recommended_sla_hours": int (how quickly this needs attention: 1, 4, 24, or 72)
}

Return ONLY the JSON object. No preamble.
"""

def build_orchestrator_tools(run_id: str) -> tuple[list[dict], dict]:
    """
    Build the spawn_worker tool and its implementation,
    scoped to a specific run_id for correlation.
    """

    workers = {
        "sentiment": SENTIMENT_WORKER,
        "action":    ACTION_WORKER,
    }

    def spawn_worker(worker_type: str, task: str) -> str:
        if worker_type not in workers:
            return json.dumps({"error": f"Unknown worker '{worker_type}'. Available: {list(workers.keys())}"})
        worker = workers[worker_type]
        return worker.run(task=task, run_id=run_id)

    tool_schema = {
        "name": "spawn_worker",
        "description": (
            "Delegate a task to a specialised worker agent. "
            "The worker runs autonomously and returns a JSON string. "
            "Worker types: 'sentiment' (tone/themes), 'action' (action items)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "worker_type": {
                    "type": "string",
                    "enum": ["sentiment", "action"],
                    "description": "Which specialised worker to invoke"
                },
                "task": {
                    "type": "string",
                    "description": (
                        "Self-contained task description including the full feedback text. "
                        "The worker has no other context."
                    )
                }
            },
            "required": ["worker_type", "task"]
        }
    }

    return [tool_schema], {"spawn_worker": spawn_worker}


def run_pipeline(feedback: str, feedback_id: str | None = None) -> dict:
    run_id = str(uuid.uuid4())[:8]
    feedback_id = feedback_id or f"FB-{run_id}"

    console.print(Panel(
        f"[bold]Feedback ID:[/bold] {feedback_id}\n\n[italic]{feedback}[/italic]",
        title="[bold cyan]Orchestrator: New Feedback[/bold cyan]"
    ))

    tools, tool_implementations = build_orchestrator_tools(run_id)

    messages = [
        {
            "role": "user",
            "content": (
                f"Analyse the following customer feedback.\n\n"
                f"Feedback ID: {feedback_id}\n\n"
                f"Feedback text:\n{feedback}"
            )
        }
    ]

    tree = Tree(f"[bold]Pipeline run {run_id}[/bold]")
    orchestrator_node = tree.add("[cyan]Orchestrator[/cyan]")

    for iteration in range(1, 8):
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            system=[{
                "type": "text",
                "text": ORCHESTRATOR_SYSTEM,
                "cache_control": {"type": "ephemeral"}
            }],
            tools=tools,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            raw = next(
                (block.text for block in response.content if hasattr(block, "text")),
                "{}"
            )
            try:
                report = json.loads(raw)
                orchestrator_node.add("[green]✓ Report generated[/green]")
                console.print(tree)
                console.print(Panel(
                    JSON(json.dumps(report, indent=2)),
                    title="[bold green]Pipeline Output[/bold green]"
                ))
                return report
            except json.JSONDecodeError:
                console.print(f"[red]Orchestrator returned non-JSON:[/red] {raw[:300]}")
                return {"error": "non_json_output", "raw": raw}

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    worker_node = orchestrator_node.add(
                        f"[yellow]→ spawn_worker({block.input.get('worker_type', '?')})[/yellow]"
                    )
                    fn = tool_implementations.get(block.name)
                    if fn:
                        result = fn(**block.input)
                    else:
                        result = json.dumps({"error": f"tool '{block.name}' not found"})

                    try:
                        parsed = json.loads(result)
                        worker_node.add(f"[green]✓ {json.dumps(parsed)[:80]}…[/green]")
                    except json.JSONDecodeError:
                        worker_node.add(f"[red]✗ non-JSON: {result[:80]}[/red]")

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            messages.append({"role": "user", "content": tool_results})

    return {"error": "max_iterations_reached"}


# ──────────────────────────────────────────────
# 4. Main
# ──────────────────────────────────────────────

SAMPLE_FEEDBACK = [
    (
        "FB-001",
        """Your platform has completely transformed how our finance team operates.
        The automated reporting saves us 3 hours a week. However, the dashboard
        crashes every time we try to export more than 1,000 rows to Excel —
        this has been happening for 2 months and we haven't heard back from support.
        If this isn't fixed soon, our VP is going to start evaluating alternatives."""
    ),
    (
        "FB-002",
        """Onboarding was smooth and the product does what it says.
        Nothing earth-shattering but it works. Would be nice to have a mobile app."""
    ),
]

if __name__ == "__main__":
    for feedback_id, feedback_text in SAMPLE_FEEDBACK:
        run_pipeline(feedback=feedback_text, feedback_id=feedback_id)
        console.print("\n" + "─" * 60 + "\n")
