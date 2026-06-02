# Concept 01 — What Is Agentic AI?

## From Chatbot to Agent: The Mental Model Shift

When you call Claude as a chatbot, the interaction is stateless and reactive:

```
User: "Summarise this document."
Claude: "Here is the summary…"
```

One prompt in, one response out. Claude has no agency — it responds to what you give it.

An **agent** is different. You give it a **goal** and it decides:

- What information it needs
- Which tools to call to get that information
- How to interpret the results
- Whether it is done, or needs to keep working

The agent loop looks like this:

```
GOAL given by user/orchestrator
    │
    ▼
┌───────────────────────────────┐
│  THINK: Do I have what I need │ ◄────────────────────┐
│         to complete the goal? │                      │
└───────────────────────────────┘                      │
    │                                                  │
    ├── YES ──► Generate final response ──► DONE       │
    │                                                  │
    └── NO  ──► Decide which tool to call              │
                    │                                  │
                    ▼                                  │
              Call the tool                            │
                    │                                  │
                    ▼                                  │
              Observe result ─────────────────────────┘
```

This loop — **think → act → observe → repeat** — is the core of every AI agent, regardless of how complex the system becomes.

---

## Why "Agentic" Matters for Enterprise

Most high-value enterprise tasks are not single-step. Consider:

- **Customer support triage**: Identify issue → look up account → check ticket history → classify severity → draft response → optionally escalate
- **Financial report generation**: Query databases → validate data → compute metrics → generate charts → write narrative → format output → send to stakeholders
- **Code review**: Fetch PR diff → understand context → check style rules → identify bugs → suggest fixes → post inline comments

None of these can be done in a single LLM call. They require iteration, tool use, memory of intermediate state, and conditional branching. That is what agents enable.

---

## The Three Dimensions of Agency

### 1. Planning
The agent must decompose a goal into steps. This can be:

- **Implicit** — Claude figures it out from the goal description
- **Explicit** — the orchestrator sends a pre-written plan as structured input
- **Reflective** — the agent plans, acts, observes results, and replans if needed (ReAct pattern)

### 2. Action (Tool Use)
Agents take actions by calling **tools** — functions defined by you that Claude can invoke. Tools are the bridge between the LLM and the real world:

| Tool Category | Examples |
|---|---|
| Information retrieval | Web search, vector store lookup, database query |
| Computation | Code execution, calculator, data transformation |
| Communication | Send email, post to Slack, create Jira ticket |
| File I/O | Read file, write file, list directory |
| API calls | Call internal microservices, call external SaaS APIs |
| Agent spawning | Create and invoke a subagent |

### 3. Memory
Agents need state across turns. Memory comes in layers:

| Layer | What it holds | Lifespan | Implementation |
|---|---|---|---|
| **In-context** | Current turn messages, tool results | One run | The messages array |
| **Scratchpad** | Reasoning notes, partial results | One run | Written to a file or variable |
| **Short-term** | Session state (user ID, conversation thread) | One session | In-memory dict or Redis |
| **Long-term** | Knowledge, past interactions, policies | Persistent | Database, vector store |

---

## The Agentic AI Spectrum

Not every use case requires a full autonomous agent. Choose the right level of autonomy:

```
CHATBOT ───────────────────────────────────────────► AUTONOMOUS AGENT

One-shot Q&A        Tools, one step        Multi-step loop        Self-directed
No tools            No iteration           Bounded iterations     Unbounded iterations
No state            No state               Session state          Persistent memory
Lowest risk         Low risk               Medium risk            Highest risk
Lowest cost         Low cost               Medium cost            Highest cost
```

**Enterprise guideline**: Start at the left. Add autonomy only when the simpler approach cannot handle the task. More autonomy means more attack surface, more cost, and harder debugging.

---

## What Claude Brings to Agentic AI

Claude is especially well-suited for enterprise agents because:

1. **Long context window** — up to 200K tokens, allowing the agent to hold large documents, long tool histories, and extensive system prompts without losing context
2. **Reliable instruction following** — Claude follows complex, multi-part system prompts accurately, critical for policy enforcement
3. **Structured output** — Claude can be instructed to return JSON reliably, enabling clean integration with downstream systems
4. **Tool use with reasoning** — Claude explains its reasoning before calling a tool, making agent decisions auditable
5. **Safety by design** — Claude refuses harmful actions even when instructed by the agent's own system prompt, providing a built-in guardrail

---

## Common Misconceptions

| Misconception | Reality |
|---|---|
| "Agents are just prompt chains" | Agents have a dynamic loop; the next step depends on observed results, not a pre-written sequence |
| "More autonomy is always better" | More autonomy = more risk, more cost, harder to audit. Use the minimum viable autonomy |
| "Agents will replace engineers" | Agents are excellent at routine, well-defined tasks; they still require human design, oversight, and correction |
| "You need RAG for enterprise agents" | Often simple retrieval (SQL query, file read) is more reliable than vector similarity; use RAG when appropriate, not by default |
| "Prompt caching is optional" | For production agents with long system prompts, caching reduces cost by 90% and latency by 60-85% — it is effectively mandatory |

---

## Key Terms

**Agentic loop** — the think-act-observe cycle that repeats until the goal is met or the budget is exhausted

**Tool call** — a structured invocation of a function by Claude, defined by a JSON schema and executed by your code

**Stop condition** — the criteria that end the loop: goal achieved, max iterations reached, budget exhausted, or error threshold hit

**ReAct** — Reasoning + Acting, a pattern where the agent reasons explicitly before each tool call (Claude does this naturally)

**HITL** — Human-in-the-Loop, a checkpoint where a human must approve before the agent continues

---

## Next

→ [Concept 02 — Agent Architecture: Anatomy of an Agent](./02-agent-architecture.md)
