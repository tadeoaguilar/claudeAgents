# Exercise 01 — Hello Agent

## Goal

Write your first agentic loop from scratch. By the end of this exercise you will:

- Understand the structure of the `messages` array
- Know what `stop_reason` means and how to handle each value
- Have a running agent that uses a simple tool

## Time Estimate

~30 minutes

## Prerequisites

- Python 3.10+
- `pip install anthropic rich python-dotenv`
- `ANTHROPIC_API_KEY` set in `.env`

---

## The Task

Build an agent that can answer arithmetic questions by calling a `calculate` tool. The agent must:

1. Receive a math question in plain English
2. Extract the calculation it needs to perform
3. Call the `calculate` tool with a Python expression
4. Return the answer

This is intentionally simple. The goal is to understand the loop structure, not the tool's complexity.

---

## Instructions

1. Read `agent.py` completely before running it
2. Run: `python agent.py`
3. Observe the output — notice when the agent thinks, when it calls the tool, and when it answers
4. Complete the three challenges below

---

## Challenges

### Challenge A — Add a second tool
Add a `lookup_exchange_rate(currency_pair: str) -> float` tool that returns a hardcoded rate (e.g., `{"USD/EUR": 0.92}`). Ask the agent: *"If I earn $5,000/month, how much is that in EUR?"*

### Challenge B — Handle a tool error
Modify `calculate` to raise a `ValueError` when it receives a division-by-zero expression. Update the agent loop to catch tool errors and send them back as error `tool_result` blocks. Ask the agent: *"What is 100 divided by 0?"* — the agent should recognise the error and explain it.

### Challenge C — Add an iteration counter
Add a counter that prints `[Turn N]` before each model call. Ask a complex question that requires multiple tool calls (e.g., *"What is (123 * 456) + (789 / 3)?"*) and observe how many turns it takes.

---

## Key Concepts Practiced

- The `messages` array accumulation pattern
- `stop_reason: "end_turn"` vs `stop_reason: "tool_use"`
- Sending `tool_result` blocks back to the model
- The agent loop termination condition

---

## Next

→ [Exercise 02 — Tool-Use Agent](../02-tool-use-agent/README.md)
