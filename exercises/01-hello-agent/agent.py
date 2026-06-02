"""
Exercise 01 — Hello Agent

The simplest possible agentic loop.
The agent answers arithmetic questions by calling a calculate() tool.

Run:
    python agent.py
"""

import ast
import os
from dotenv import load_dotenv
import anthropic
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
console = Console()

# ──────────────────────────────────────────────
# 1. Tool implementation
# ──────────────────────────────────────────────

def calculate(expression: str) -> str:
    """
    Safely evaluate a Python arithmetic expression.
    Only allows numbers and basic operators: + - * / ** ( )
    """
    # Whitelist: only safe arithmetic characters
    allowed_chars = set("0123456789 +-*/().e")
    if not all(c in allowed_chars for c in expression):
        return f"Error: unsafe expression '{expression}'"

    try:
        # ast.literal_eval only handles literals; we use compile+eval for arithmetic
        # with a restricted namespace (no builtins)
        code = compile(expression, "<string>", "eval")
        result = eval(code, {"__builtins__": {}}, {})  # noqa: S307
        return str(result)
    except ZeroDivisionError:
        return "Error: division by zero"
    except Exception as e:
        return f"Error: {e}"


# ──────────────────────────────────────────────
# 2. Tool schema (what the model sees)
# ──────────────────────────────────────────────

TOOLS = [
    {
        "name": "calculate",
        "description": (
            "Evaluate a Python arithmetic expression. "
            "Use standard Python syntax: +, -, *, /, **, and parentheses. "
            "Example: calculate('(3 + 4) * 2') → '14'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "A Python arithmetic expression using numbers and operators only."
                }
            },
            "required": ["expression"]
        }
    }
]

TOOL_REGISTRY = {
    "calculate": calculate,
}

# ──────────────────────────────────────────────
# 3. System prompt
# ──────────────────────────────────────────────

SYSTEM_PROMPT = """You are a precise arithmetic assistant.

When the user asks a math question:
1. Identify the arithmetic operations needed
2. Call the calculate tool with a Python expression
3. Interpret the result and answer in plain English

Always show your work: explain what you calculated before giving the final answer.
"""

# ──────────────────────────────────────────────
# 4. The agent loop
# ──────────────────────────────────────────────

def run_agent(user_question: str, max_iterations: int = 10) -> str:
    """
    Core agentic loop.

    Maintains a growing messages list:
      user question → assistant (tool call) → user (tool result) → assistant (answer)
    """
    messages = [
        {"role": "user", "content": user_question}
    ]

    console.print(Panel(f"[bold cyan]Goal:[/bold cyan] {user_question}", title="Agent Starting"))

    for iteration in range(1, max_iterations + 1):
        console.print(f"\n[dim]── Turn {iteration} ──[/dim]")

        # Call the model
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",   # Use Haiku for exercises (cost-efficient)
            max_tokens=1024,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},  # Cache the system prompt
                }
            ],
            tools=TOOLS,
            messages=messages,
        )

        # Log token usage
        console.print(
            f"  [dim]Tokens: {response.usage.input_tokens} in / "
            f"{response.usage.output_tokens} out | "
            f"stop_reason: {response.stop_reason}[/dim]"
        )

        # Append assistant response to history
        messages.append({"role": "assistant", "content": response.content})

        # ── Case 1: Model is done ──
        if response.stop_reason == "end_turn":
            final_text = next(
                (block.text for block in response.content if hasattr(block, "text")),
                "(no text response)"
            )
            console.print(Panel(
                f"[green]{final_text}[/green]",
                title="[bold green]Final Answer[/bold green]"
            ))
            return final_text

        # ── Case 2: Model wants to call tools ──
        if response.stop_reason == "tool_use":
            tool_results = []

            for block in response.content:
                if block.type == "tool_use":
                    console.print(f"  [yellow]Tool call:[/yellow] {block.name}({block.input})")

                    tool_fn = TOOL_REGISTRY.get(block.name)
                    if tool_fn is None:
                        result = f"Error: tool '{block.name}' is not available"
                    else:
                        result = tool_fn(**block.input)

                    console.print(f"  [yellow]Tool result:[/yellow] {result}")

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            # Send all tool results back to the model in a single user message
            messages.append({"role": "user", "content": tool_results})

    return "Error: agent reached maximum iterations without completing."


# ──────────────────────────────────────────────
# 5. Main
# ──────────────────────────────────────────────

if __name__ == "__main__":
    questions = [
        "What is 1,234 multiplied by 5,678?",
        "If I have $10,000 and spend 37% of it, how much do I have left?",
        "What is the square root of 2 to 6 decimal places? Use ** 0.5",
    ]

    for question in questions:
        run_agent(question)
        console.print("\n" + "─" * 60 + "\n")
