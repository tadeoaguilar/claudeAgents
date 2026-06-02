# Concept 03 — Subagents and Orchestration

## Why Multiple Agents?

A single agent with all capabilities is tempting to build but problematic in production:

| Problem | Impact |
|---|---|
| One long context handles everything | Context pollutes across unrelated steps; errors in step 2 affect step 5 |
| One agent, all permissions | If compromised or misbehaving, blast radius is maximised |
| All logic in one system prompt | Prompt grows unwieldy; behaviour becomes harder to predict |
| Sequential by default | No parallelism; slow for independent tasks |

Multi-agent systems solve these problems by **decomposing** a complex task into focused subtasks, each owned by a specialised agent.

---

## Orchestrator and Worker Pattern

The most common enterprise pattern:

```
                ┌─────────────────────────┐
                │    ORCHESTRATOR AGENT   │
                │                         │
                │  Receives the goal      │
                │  Decomposes into tasks  │
                │  Delegates to workers   │
                │  Merges results         │
                │  Returns final answer   │
                └────────────┬────────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
     ┌────────────┐ ┌────────────┐ ┌────────────┐
     │  WORKER A  │ │  WORKER B  │ │  WORKER C  │
     │ (Research) │ │  (SQL/DB)  │ │  (Writer)  │
     │            │ │            │ │            │
     │ Tools:     │ │ Tools:     │ │ Tools:     │
     │ web_search │ │ query_db   │ │ read_file  │
     │ fetch_page │ │ run_python │ │ send_email │
     └────────────┘ └────────────┘ └────────────┘
```

**Key design decisions:**

1. **What does the orchestrator know?** — Only the task decomposition and coordination logic. It should not need domain knowledge that belongs to workers.
2. **What can workers access?** — Only the tools required for their specific task. No cross-contamination.
3. **How do workers communicate?** — Through the orchestrator, never directly. This keeps the graph acyclic and auditable.

---

## Implementing a Subagent

A subagent is just an agent invoked by another agent through a tool. You define a `spawn_agent` tool that the orchestrator can call:

```python
def spawn_agent(
    task: str,
    agent_type: str,
    context: dict | None = None
) -> str:
    """
    Runs a specialised subagent and returns its result as a string.
    The orchestrator calls this tool; the implementation runs a full agent loop.
    """
    agent_config = AGENT_REGISTRY[agent_type]  # system prompt + tools for this type
    return run_agent(
        user_goal=task,
        system_prompt=agent_config["system_prompt"],
        tools=agent_config["tools"],
        context=context,
    )
```

The orchestrator's tool definition:

```python
{
    "name": "spawn_agent",
    "description": (
        "Delegate a self-contained task to a specialised subagent. "
        "The subagent runs autonomously and returns a result string. "
        "Use this for: research, database queries, writing, or any task "
        "that requires a specific set of tools."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "Clear, self-contained description of what the subagent must do and what it must return"
            },
            "agent_type": {
                "type": "string",
                "enum": ["research", "database", "writer"],
                "description": "The type of specialised agent to use"
            },
            "context": {
                "type": "object",
                "description": "Optional key-value context to pass to the subagent (e.g., user_id, date_range)"
            }
        },
        "required": ["task", "agent_type"]
    }
}
```

---

## Orchestration Patterns in Detail

### Pattern 1: Sequential Pipeline

Each stage's output becomes the next stage's input. Suitable when stages have hard dependencies.

```
Input ──► Stage A ──► Stage B ──► Stage C ──► Output
```

```python
result_a = spawn_agent("Extract all financial figures from this document", "research", {"document": doc})
result_b = spawn_agent(f"Validate these figures against the database: {result_a}", "database")
result_c = spawn_agent(f"Write an executive summary using these validated figures: {result_b}", "writer")
```

**Risk**: A failure in Stage B blocks Stage C. Add retry logic and clear error propagation.

---

### Pattern 2: Parallel Fan-Out

Orchestrator sends independent tasks to multiple workers simultaneously, then merges results.

```
         ┌──► Worker A ──┐
Input ───┼──► Worker B ──┼──► Merge ──► Output
         └──► Worker C ──┘
```

```python
import asyncio

async def run_parallel_agents(tasks: list[dict]) -> list[str]:
    coroutines = [
        asyncio.to_thread(spawn_agent, task["task"], task["agent_type"])
        for task in tasks
    ]
    return await asyncio.gather(*coroutines)

tasks = [
    {"task": "Get EMEA Q3 revenue",   "agent_type": "database"},
    {"task": "Get APAC Q3 revenue",   "agent_type": "database"},
    {"task": "Get AMER Q3 revenue",   "agent_type": "database"},
]
results = asyncio.run(run_parallel_agents(tasks))
```

**Risk**: Context pollution if workers share state. Ensure workers are stateless.

---

### Pattern 3: Map-Reduce

Fan-out over a large input corpus, collect results, then reduce into a final answer.

```
Large Input
    │
    ├──► Chunk 1 ──► Agent ──► Summary 1 ──┐
    ├──► Chunk 2 ──► Agent ──► Summary 2 ──┼──► Reducer ──► Final
    └──► Chunk 3 ──► Agent ──► Summary 3 ──┘
```

Useful for: analysing hundreds of support tickets, reviewing a large codebase, processing many documents.

```python
def map_reduce(documents: list[str], question: str) -> str:
    chunk_size = 10
    chunks = [documents[i:i+chunk_size] for i in range(0, len(documents), chunk_size)]

    # MAP: summarise each chunk
    chunk_summaries = []
    for chunk in chunks:
        summary = spawn_agent(
            f"Summarise the following documents with respect to: {question}\n\nDocuments:\n" +
            "\n---\n".join(chunk),
            "research"
        )
        chunk_summaries.append(summary)

    # REDUCE: synthesise all summaries
    return spawn_agent(
        f"Synthesise these summaries to answer: {question}\n\nSummaries:\n" +
        "\n---\n".join(chunk_summaries),
        "writer"
    )
```

---

### Pattern 4: Critic-Revise

A generator agent produces output; a critic agent evaluates it; if quality is insufficient, the generator revises. Cap iterations to prevent infinite loops.

```
Goal ──► Generator ──► Draft ──► Critic ──► Score ──► if score < threshold ──► Generator (revise)
                                                    └──► if score >= threshold ──► Output
```

```python
MAX_REVISIONS = 3

def critic_revise(goal: str) -> str:
    draft = spawn_agent(f"Write a response for: {goal}", "writer")

    for _ in range(MAX_REVISIONS):
        critique = spawn_agent(
            f"Evaluate this response on a scale of 1-10 for accuracy, clarity, and completeness. "
            f"Return JSON: {{\"score\": int, \"feedback\": str}}\n\nGoal: {goal}\nResponse: {draft}",
            "research"
        )
        critique_data = json.loads(critique)

        if critique_data["score"] >= 8:
            return draft  # Acceptable quality

        draft = spawn_agent(
            f"Revise this response based on the feedback.\n\n"
            f"Goal: {goal}\nCurrent draft: {draft}\nFeedback: {critique_data['feedback']}",
            "writer"
        )

    return draft  # Return best effort after max revisions
```

---

## Task Specification: Writing Good Subagent Prompts

The quality of your orchestrator's task prompts determines the quality of subagent output. Good task prompts are:

**Self-contained** — the subagent has everything it needs without needing to ask follow-up questions

**Specific about output format** — "Return a JSON object with keys: `revenue`, `region`, `quarter`"

**Clear about scope** — "Only consider data from Q3 2025. Ignore prior quarters."

**Explicit about what NOT to do** — "Do not send any emails. Only retrieve and return data."

Bad prompt:
```
"Get the revenue data and analyse it"
```

Good prompt:
```
"Query the sales database to get total revenue grouped by region for Q3 2025 (July-September 2025).
Return a JSON array: [{\"region\": str, \"revenue\": float, \"currency\": \"USD\"}].
Only use the sales_fact table. Do not aggregate across other time periods."
```

---

## Avoiding Common Multi-Agent Mistakes

| Mistake | Consequence | Fix |
|---|---|---|
| Passing raw tool results between agents | Context bloat; sensitive data leakage | Summarise and filter before passing |
| Orchestrator reimplements worker logic | Duplication; inconsistency | Orchestrator only delegates; never does domain work |
| Workers with overlapping tool access | Security boundary breaks | Each worker has a minimal, non-overlapping tool set |
| No correlation IDs across agents | Impossible to trace a multi-agent run | Pass a `run_id` through all spawn calls |
| Infinite delegation loops | Runaway cost | Hard cap: orchestrator cannot spawn more than N agents per run |
| Agent results not validated | Bad data propagates silently | Parse and validate structured output before passing downstream |

---

## Isolation and Security Boundaries

Each agent in a multi-agent system should be treated as a trust boundary:

```
ORCHESTRATOR (high trust)
    │
    │  passes: task string + context dict
    │  receives: result string (treated as untrusted input)
    │
    ▼
WORKER (lower trust)
    │
    │  can call: only its assigned tools
    │  cannot call: tools of other workers
    │  cannot: spawn further agents (unless explicitly granted)
```

**Always validate and sanitise the output of a subagent before using it** — treat it like untrusted user input. A compromised or misbehaving subagent should not be able to inject instructions into the orchestrator.

---

## Next

→ [Concept 04 — Skills: Reusable Workflows](./04-skills.md)
