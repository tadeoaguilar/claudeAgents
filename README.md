# Enterprise Agentic AI with Claude

A comprehensive reference repository for building, deploying, and maintaining production-grade AI agents using the Anthropic Claude API and Claude Code platform.

---

## Table of Contents

1. [What Is This Repository?](#what-is-this-repository)
2. [Core Concepts at a Glance](#core-concepts-at-a-glance)
3. [The Agentic AI Stack](#the-agentic-ai-stack)
4. [Repository Structure](#repository-structure)
5. [Prerequisites](#prerequisites)
6. [Learning Path](#learning-path)
7. [Key Design Principles for Enterprise Agents](#key-design-principles-for-enterprise-agents)
8. [Quick Reference: Agent Taxonomy](#quick-reference-agent-taxonomy)
9. [Quick Reference: Orchestration Patterns](#quick-reference-orchestration-patterns)
10. [Quick Reference: Enterprise Checklist](#quick-reference-enterprise-checklist)
11. [Further Reading](#further-reading)

---

## What Is This Repository?

This repository teaches you how to move from calling Claude as a chatbot to building **autonomous, multi-step systems** that reason, act, and collaborate to complete complex enterprise workflows.

It covers:

- **Agents** — autonomous Claude instances that decide which actions to take, in what order, using tools
- **Subagents** — specialised child agents orchestrated by a parent, each with scoped capabilities
- **Skills** — reusable, invokable workflows that encapsulate domain logic and can be shared across agents
- **Deployment lifecycle** — from local prototype to production system with CI/CD, monitoring, and cost control
- **Enterprise concerns** — security, compliance, observability, human-in-the-loop, and multi-tenancy

---

## Core Concepts at a Glance

| Concept | One-Line Definition | Scope |
|---|---|---|
| **Agent** | A Claude instance with tools that iterates until a goal is met | Full autonomy over a task |
| **Orchestrator** | An agent that plans work and delegates to subagents | Coordinates other agents |
| **Subagent** | A specialised agent invoked by an orchestrator | Scoped, bounded task |
| **Skill** | A named, reusable workflow invoked with a slash command or tool call | Encapsulated logic |
| **Tool** | A function the agent can call (search, code exec, DB query, API call…) | Single action |
| **Memory** | Persistent state across agent turns (file, DB, vector store) | Cross-turn context |
| **Human-in-the-Loop (HITL)** | A checkpoint where a human approves before the agent proceeds | Governance gate |
| **Prompt Caching** | Reusing the KV cache for long system prompts to cut cost and latency | Cost optimisation |

---

## The Agentic AI Stack

```
┌─────────────────────────────────────────────────────────────┐
│                    ENTERPRISE APPLICATION                    │
│         (web app, internal tool, scheduled job, API)         │
├─────────────────────────────────────────────────────────────┤
│                     ORCHESTRATION LAYER                      │
│   Orchestrator Agent  →  Task planning  →  Delegation        │
├──────────────────┬──────────────────┬───────────────────────┤
│   Subagent A     │   Subagent B     │   Subagent C          │
│   (Research)     │   (Code/SQL)     │   (Communication)     │
├──────────────────┴──────────────────┴───────────────────────┤
│                        TOOL LAYER                            │
│  Web Search │ Code Exec │ DB Query │ APIs │ File I/O │ Email │
├─────────────────────────────────────────────────────────────┤
│                      MEMORY LAYER                            │
│       Short-term (context) │ Long-term (DB / vector store)   │
├─────────────────────────────────────────────────────────────┤
│                     OBSERVABILITY LAYER                      │
│        Structured Logging │ Metrics │ Traces │ Alerts        │
└─────────────────────────────────────────────────────────────┘
```

---

## Repository Structure

```
claudeAgents/
│
├── README.md                        ← YOU ARE HERE (start here)
│
├── concepts/
│   ├── 01-what-is-agentic-ai.md     ← Mental model: from chatbot to agent
│   ├── 02-agent-architecture.md     ← Anatomy of an agent: loop, tools, memory
│   ├── 03-subagents-orchestration.md← Multi-agent patterns and delegation
│   ├── 04-skills.md                 ← Reusable skills and command design
│   ├── 05-enterprise-patterns.md    ← HITL, approval workflows, multi-tenancy
│   ├── 06-deployment-lifecycle.md   ← From prototype to production
│   └── 07-observability.md          ← Logging, metrics, tracing, cost control
│
├── exercises/
│   ├── 01-hello-agent/              ← Write your first agentic loop
│   ├── 02-tool-use-agent/           ← Give an agent real tools
│   ├── 03-multi-agent-pipeline/     ← Orchestrator + subagents
│   ├── 04-enterprise-workflow/      ← HITL, retries, audit trail
│   └── 05-observability/            ← Structured logging + cost tracking
│
└── examples/
    ├── customer-support/            ← Triage + resolution + escalation agent
    ├── data-analyst/                ← SQL + chart generation + report agent
    └── code-reviewer/               ← PR review agent with inline comments
```

---

## Prerequisites

### Knowledge
- Python 3.10+ (all exercises use Python)
- Familiarity with REST APIs and JSON
- Basic understanding of LLMs (prompt/response cycle)

### Accounts and Keys
- Anthropic API key — set `ANTHROPIC_API_KEY` in your environment
- Optionally: a database (SQLite bundled with exercises), GitHub token for code-review examples

### Installation

```bash
# Clone the repo
cd claudeAgents

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# Install dependencies
pip install anthropic rich python-dotenv
```

Create a `.env` file in the repo root:

```
ANTHROPIC_API_KEY=sk-ant-...
```

---

## Learning Path

Follow these in order for a structured progression from fundamentals to production systems.

```
BEGINNER
    │
    ▼
concepts/01  →  exercises/01   (mental model + first agent)
    │
    ▼
concepts/02  →  exercises/02   (architecture + tools)
    │
    ▼
concepts/03  →  exercises/03   (subagents + orchestration)
    │
    ▼
concepts/04                    (skills theory)
    │
    ▼
concepts/05  →  exercises/04   (enterprise: HITL, retries, audit)
    │
    ▼
concepts/06                    (deployment lifecycle)
    │
    ▼
concepts/07  →  exercises/05   (observability)
    │
    ▼
examples/    (customer-support, data-analyst, code-reviewer)
    │
    ▼
PRODUCTION-READY
```

---

## Key Design Principles for Enterprise Agents

### 1. Minimal Footprint
Grant agents only the tools they need for their specific task. A customer-support agent does not need database write access; a reporting agent does not need the ability to send emails.

### 2. Explicit Over Implicit
Every decision point that has downstream business impact should be logged and, where appropriate, require human approval. Never let an agent take an irreversible action silently.

### 3. Fail Loud, Recover Gracefully
Agents should surface errors clearly and return structured error objects rather than guessing. Retries should be bounded with exponential backoff. Unrecoverable failures should escalate to humans.

### 4. Prompt Caching by Default
Long system prompts — especially those encoding company policies, tool schemas, and examples — should use `cache_control: {type: "ephemeral"}` to avoid paying token costs on every call.

### 5. Structured Outputs Everywhere
Use `response_format` or instruct agents to return JSON. Unstructured prose outputs cannot be reliably parsed, audited, or handed to downstream systems.

### 6. Budget Awareness
Each agent invocation should know its token budget and time budget. Orchestrators should be able to stop and report partial results rather than running forever.

### 7. Human-in-the-Loop at the Right Altitude
Not every step needs human approval — that defeats the purpose of automation. Design HITL gates for: high-cost actions, irreversible actions, low-confidence decisions, and compliance checkpoints.

---

## Quick Reference: Agent Taxonomy

```
SINGLE AGENT
  └─ One Claude instance, one task, direct tool calls
  └─ Best for: focused, bounded tasks (summarise, classify, translate)

ORCHESTRATOR + WORKERS
  └─ One planner agent delegates to N specialised workers
  └─ Best for: complex tasks with distinct phases (research → draft → review)

PIPELINE (SEQUENTIAL)
  └─ Agent A output → Agent B input → Agent C input
  └─ Best for: ETL-style workflows (extract → transform → load)

PARALLEL SWARM
  └─ Orchestrator fans out to N workers simultaneously, collects results
  └─ Best for: batch processing, parallel analysis of multiple documents

AUTONOMOUS LOOP (CRON-DRIVEN)
  └─ Agent wakes on a schedule, checks state, acts, sleeps
  └─ Best for: monitoring, scheduled reports, alert triage
```

---

## Quick Reference: Orchestration Patterns

| Pattern | When to Use | Risk |
|---|---|---|
| **Sequential pipeline** | Steps have hard dependencies | Single point of failure |
| **Parallel fan-out** | Steps are independent | Coordination complexity |
| **Map-reduce** | Large input, summarise across chunks | Context budget management |
| **Critic-revise** | Quality must exceed a threshold | Infinite loop risk — cap iterations |
| **Supervisor** | Worker agents need oversight + correction | Added latency per turn |
| **Hierarchical** | Complex decomposition across many domains | Debugging depth |

---

## Quick Reference: Enterprise Checklist

Use this before promoting any agent to production:

**Security**
- [ ] API keys in environment variables or secrets manager, never in code
- [ ] Agent has least-privilege tool access
- [ ] All tool inputs validated and sanitised
- [ ] PII stripped or masked before logging

**Reliability**
- [ ] Retries with exponential backoff on API errors
- [ ] Max iteration cap to prevent infinite loops
- [ ] Graceful degradation when a tool is unavailable
- [ ] Structured error objects returned (not bare exceptions)

**Observability**
- [ ] Every agent turn logged with: model, tokens, latency, cost
- [ ] Tool calls logged with input, output, duration
- [ ] Correlation IDs for tracing multi-agent runs
- [ ] Alerts on: error rate, p99 latency, cost per run

**Compliance**
- [ ] Audit trail persisted to immutable store
- [ ] Human approval gate for irreversible actions
- [ ] Data retention policy applied to logs
- [ ] Model version pinned in production

**Cost**
- [ ] Prompt caching enabled for static system prompts
- [ ] Token budgets enforced per run
- [ ] Batch API used for non-real-time workloads
- [ ] Cost-per-run tracked and alerted on anomalies

---

## Further Reading

- [Anthropic API Documentation](https://docs.anthropic.com)
- [Claude Model Overview](https://docs.anthropic.com/en/docs/about-claude/models)
- [Tool Use Guide](https://docs.anthropic.com/en/docs/build-with-claude/tool-use)
- [Prompt Caching Guide](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching)
- [Anthropic Responsible Scaling Policy](https://www.anthropic.com/news/responsible-scaling-policy)
- [Building Effective Agents (Anthropic Cookbook)](https://github.com/anthropics/anthropic-cookbook/tree/main/patterns/agents)
