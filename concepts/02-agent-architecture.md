# Concept 02 — Agent Architecture: Anatomy of an Agent

## The Four Components of Every Agent

Every Claude agent, no matter how complex, is built from four components:

```
┌──────────────────────────────────────────────────────────────┐
│                          AGENT                               │
│                                                              │
│  ┌────────────┐   ┌────────────┐   ┌────────────────────┐   │
│  │  SYSTEM    │   │  MEMORY    │   │       TOOLS        │   │
│  │  PROMPT    │   │  (state)   │   │  (actions it can   │   │
│  │  (persona, │   │            │   │   take)            │   │
│  │   policy,  │   │            │   │                    │   │
│  │   tools)   │   │            │   │                    │   │
│  └─────┬──────┘   └─────┬──────┘   └────────┬───────────┘   │
│        │                │                   │               │
│        └────────────────┼───────────────────┘               │
│                         │                                    │
│                  ┌──────▼──────┐                            │
│                  │    MODEL    │                             │
│                  │  (Claude)   │                             │
│                  └─────────────┘                            │
└──────────────────────────────────────────────────────────────┘
```

### Component 1: System Prompt
The system prompt defines:
- **Persona** — who the agent is and what it is responsible for
- **Policy** — what it must always do, must never do, and when to escalate
- **Tool schema** — the list of available tools and how to use them
- **Output format** — the required structure of final responses
- **Examples** — few-shot demonstrations of correct behaviour

The system prompt is the most important lever you have for controlling agent behaviour. In production, it is often 2,000–10,000 tokens. **Always cache it.**

### Component 2: Memory (State)
Memory is carried in the `messages` array sent to the API on each turn:

```python
messages = [
    {"role": "user",      "content": "Analyse Q3 revenue by region"},
    {"role": "assistant", "content": [...tool_use blocks...]},
    {"role": "user",      "content": [...tool_result blocks...]},
    {"role": "assistant", "content": "Based on the query results..."},
]
```

As the loop progresses, tool calls and their results accumulate in this array. This gives Claude the full history of what it has tried and observed.

For long-running agents, you must manage context size: summarise old turns, truncate distant history, or offload to external storage.

### Component 3: Tools
Tools are Python functions wrapped in a JSON schema that Claude can call. The schema tells Claude what the tool does, what parameters it takes, and what it returns.

```python
tools = [
    {
        "name": "query_database",
        "description": "Run a read-only SQL query against the data warehouse. Returns rows as JSON.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "A valid SELECT statement. No DDL or DML."
                }
            },
            "required": ["sql"]
        }
    }
]
```

When Claude decides to call this tool, it returns a structured `tool_use` block:

```json
{
  "type": "tool_use",
  "id": "toolu_01abc",
  "name": "query_database",
  "input": { "sql": "SELECT region, SUM(revenue) FROM sales WHERE quarter='Q3' GROUP BY region" }
}
```

Your code executes the function and sends back a `tool_result`:

```json
{
  "type": "tool_result",
  "tool_use_id": "toolu_01abc",
  "content": "[{\"region\": \"EMEA\", \"revenue\": 4200000}, ...]"
}
```

### Component 4: Model
The model processes the system prompt, the message history, and the tool definitions, and produces either a final text response or a tool call. In production:

- Pin the model version (e.g., `claude-opus-4-8`) — never use a pointer like `latest` in production
- Use `max_tokens` to cap output length
- Use `temperature: 1` (default) for tool use; lower temperature only for highly constrained classification tasks

---

## The Full Agent Loop in Code

This is the canonical pattern. Every exercise in this repo builds on it.

```python
import anthropic
import json

client = anthropic.Anthropic()
MODEL = "claude-opus-4-8"

SYSTEM_PROMPT = """You are a data analyst agent. You have access to the company's data warehouse
via the query_database tool. Answer questions by querying the database and analysing results.

Always:
- Validate your SQL before calling the tool
- Return structured JSON in your final response
- Explain your reasoning before each tool call

Never:
- Run INSERT, UPDATE, DELETE, or DROP statements
- Return PII in your final response
"""

def query_database(sql: str) -> str:
    # In a real implementation, this connects to your database
    return json.dumps([{"region": "EMEA", "revenue": 4200000}])

TOOLS = [
    {
        "name": "query_database",
        "description": "Run a read-only SQL SELECT query against the data warehouse.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "A valid SELECT statement"}
            },
            "required": ["sql"]
        }
    }
]

TOOL_REGISTRY = {
    "query_database": query_database,
}

def run_agent(user_goal: str, max_iterations: int = 10) -> str:
    messages = [{"role": "user", "content": user_goal}]

    for iteration in range(max_iterations):
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"}  # Cache the system prompt
                }
            ],
            tools=TOOLS,
            messages=messages,
        )

        # Append assistant response to history
        messages.append({"role": "assistant", "content": response.content})

        # If Claude stopped naturally (no tool calls), we are done
        if response.stop_reason == "end_turn":
            return response.content[0].text

        # If Claude wants to use tools, execute them
        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_fn = TOOL_REGISTRY.get(block.name)
                    if tool_fn is None:
                        result = f"Error: unknown tool '{block.name}'"
                    else:
                        result = tool_fn(**block.input)

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            messages.append({"role": "user", "content": tool_results})

    return "Max iterations reached without completing the goal."

if __name__ == "__main__":
    result = run_agent("What was total revenue by region in Q3?")
    print(result)
```

---

## Stop Reasons

Claude signals intent through `stop_reason`:

| `stop_reason` | Meaning | Your code should |
|---|---|---|
| `"end_turn"` | Claude is done — final response ready | Extract and return the response |
| `"tool_use"` | Claude wants to call one or more tools | Execute tools, append results, continue loop |
| `"max_tokens"` | Response hit the `max_tokens` limit | Increase limit, or summarise and retry |
| `"stop_sequence"` | A custom stop sequence was triggered | Handle per your design |

---

## Parallel Tool Calls

Claude can request multiple tool calls in a single turn. Always handle them all before sending results back:

```python
if response.stop_reason == "tool_use":
    tool_results = []
    for block in response.content:
        if block.type == "tool_use":
            result = execute_tool(block.name, block.input)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result,
            })
    # Send ALL results back in a single message
    messages.append({"role": "user", "content": tool_results})
```

You can execute these tool calls in parallel using `asyncio` or `ThreadPoolExecutor` for significant performance gains in production.

---

## Context Management at Scale

The agent loop accumulates tokens on every turn. Left unmanaged, you will hit the context limit and fail mid-task.

**Strategies:**

1. **Summarise old turns** — After N turns, ask Claude to summarise all prior results into a compact note, then truncate the history to just that summary
2. **Offload to external memory** — Store tool results in a file or database, pass only references in the messages array
3. **Structured scratchpad** — Have the agent maintain a JSON "working notes" file it reads/writes per turn; only the current state is in context
4. **Sliding window** — Keep only the last N messages; older context is dropped

---

## Token Budget and Cost

Track token usage on every call:

```python
response = client.messages.create(...)
print(f"Input tokens:  {response.usage.input_tokens}")
print(f"Output tokens: {response.usage.output_tokens}")
print(f"Cache read:    {response.usage.cache_read_input_tokens}")
print(f"Cache created: {response.usage.cache_creation_input_tokens}")
```

**Approximate costs (Opus 4.8, as of mid-2025):**
- Input: $15 / 1M tokens
- Output: $75 / 1M tokens
- Cache write: $18.75 / 1M tokens
- Cache read: $1.50 / 1M tokens

A long system prompt (5,000 tokens) cached across 1,000 runs saves ~$73 vs. uncached. **Always cache your system prompt.**

---

## Next

→ [Concept 03 — Subagents and Orchestration](./03-subagents-orchestration.md)
