# Concept 04 — Skills: Reusable Agentic Workflows

## What Is a Skill?

A **skill** is a named, reusable workflow that encapsulates domain logic an agent can invoke by name — without needing to re-derive the steps each time.

Think of skills as the equivalent of a well-tested internal library function, but for agentic behaviour:

- A function encapsulates reusable *computation*
- A skill encapsulates reusable *agentic reasoning + tool usage*

In the Claude Code platform (the CLI/IDE tool you are using right now), skills are invoked with `/skill-name` and implemented as slash commands in CLAUDE.md or as separate skill files. In the Anthropic API, skills are implemented as **tool calls**, **prompt templates**, or **agent configurations** registered in a skill registry.

---

## Skills in the Claude Code Context

When you type `/code-review` or `/simplify` in Claude Code, you are invoking a skill. Each skill:

1. Has a name and description (so Claude knows when to apply it)
2. Has a defined behaviour (what steps it takes, what tools it uses)
3. Returns a predictable output type
4. Can be composed with other skills

You can define custom skills for your team by adding them to `.claude/commands/` as markdown files. Claude Code loads them as slash commands.

Example custom skill file — `.claude/commands/summarise-pr.md`:

```markdown
# Summarise PR

Read the current git diff and produce a structured PR summary with:
- One-sentence description
- Bulleted list of changes
- Risk assessment (Low / Medium / High) with justification
- Suggested reviewers based on changed file ownership

Output as markdown.
```

Any team member can then invoke `/summarise-pr` and get consistent, high-quality PR summaries without writing the prompt from scratch each time.

---

## Skills in the API Context

In the API, skills are implemented as reusable functions that configure an agent for a specific task. A skill registry stores them:

```python
from dataclasses import dataclass
from typing import Callable

@dataclass
class Skill:
    name: str
    description: str
    system_prompt: str
    tools: list[dict]
    output_schema: dict | None = None  # JSON schema for the expected output

SKILL_REGISTRY: dict[str, Skill] = {}

def register_skill(skill: Skill) -> None:
    SKILL_REGISTRY[skill.name] = skill

def get_skill(name: str) -> Skill:
    if name not in SKILL_REGISTRY:
        raise ValueError(f"Skill '{name}' not found. Available: {list(SKILL_REGISTRY.keys())}")
    return SKILL_REGISTRY[name]
```

---

## Designing a Skill

A well-designed skill has five properties:

### 1. Clear Trigger Condition
When should this skill be invoked vs. a different one? The description must be unambiguous.

Bad: `"Analyse data"`
Good: `"Analyse structured tabular data from a database query and return statistical summaries (mean, median, std dev, outliers) as JSON"`

### 2. Minimal Dependencies
A skill should work with only the inputs you provide it. It should not depend on global state or assume knowledge from a previous skill's run.

### 3. Deterministic Output Schema
Define exactly what the skill returns. Use JSON schemas. Downstream code should never need to guess the shape of a skill's output.

```python
REVENUE_ANALYSIS_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "period": {"type": "string"},
        "total_revenue": {"type": "number"},
        "by_region": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "region": {"type": "string"},
                    "revenue": {"type": "number"},
                    "pct_of_total": {"type": "number"}
                },
                "required": ["region", "revenue", "pct_of_total"]
            }
        },
        "top_product": {"type": "string"},
        "anomalies": {"type": "array", "items": {"type": "string"}}
    },
    "required": ["period", "total_revenue", "by_region"]
}
```

### 4. Failure Modes Documented
Document what happens when the skill fails: does it return an error object? raise an exception? return partial results?

### 5. Cost Estimate
Skills that use large context or many tool calls should document their approximate token cost so the orchestrator can make informed decisions about when to invoke them.

---

## Example: Defining and Using a Skill

```python
import anthropic
import json

client = anthropic.Anthropic()

# Define the skill
REVENUE_ANALYSIS_SKILL = Skill(
    name="revenue_analysis",
    description=(
        "Analyse quarterly revenue data from the data warehouse. "
        "Returns a structured breakdown by region, product, and trend. "
        "Approximate cost: 2,000-5,000 tokens per run."
    ),
    system_prompt="""You are a financial data analyst. Your task is to analyse revenue data
retrieved from the data warehouse and produce a structured report.

Always:
- Query for the exact period specified, no broader
- Return valid JSON matching the provided output schema
- Flag any data anomalies you detect (missing data, outliers)

Never:
- Extrapolate or estimate figures you did not retrieve from the database
- Include PII such as customer names or contact details
""",
    tools=[
        {
            "name": "query_database",
            "description": "Run a read-only SQL query against the data warehouse.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "A valid SELECT statement"}
                },
                "required": ["sql"]
            }
        }
    ],
    output_schema=REVENUE_ANALYSIS_OUTPUT_SCHEMA
)

register_skill(REVENUE_ANALYSIS_SKILL)


def run_skill(skill_name: str, task: str, tool_implementations: dict) -> dict:
    """Execute a skill and return its structured output."""
    skill = get_skill(skill_name)
    messages = [{"role": "user", "content": task}]

    for _ in range(10):  # Max iterations
        response = client.messages.create(
            model="claude-opus-4-8",
            max_tokens=4096,
            system=[{
                "type": "text",
                "text": skill.system_prompt,
                "cache_control": {"type": "ephemeral"}
            }],
            tools=skill.tools,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            raw_output = response.content[0].text
            # Parse and validate against output schema
            try:
                return json.loads(raw_output)
            except json.JSONDecodeError:
                raise ValueError(f"Skill '{skill_name}' did not return valid JSON: {raw_output}")

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    fn = tool_implementations.get(block.name)
                    result = fn(**block.input) if fn else f"Error: tool '{block.name}' not implemented"
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(result),
                    })
            messages.append({"role": "user", "content": tool_results})

    raise RuntimeError(f"Skill '{skill_name}' exceeded max iterations")


# Usage
result = run_skill(
    skill_name="revenue_analysis",
    task="Analyse Q3 2025 revenue broken down by region and product line.",
    tool_implementations={"query_database": my_db_query_function}
)
print(json.dumps(result, indent=2))
```

---

## Skill Composition

Skills can be composed: the output of one skill becomes the input of another.

```python
def quarterly_report_pipeline(quarter: str, year: int) -> str:
    """Compose multiple skills to produce a quarterly report."""

    # Skill 1: pull and analyse the revenue data
    revenue_data = run_skill(
        "revenue_analysis",
        f"Analyse {quarter} {year} revenue by region and product",
        DB_TOOLS
    )

    # Skill 2: identify risks based on the analysis
    risk_data = run_skill(
        "risk_identification",
        f"Identify business risks from this revenue analysis: {json.dumps(revenue_data)}",
        RESEARCH_TOOLS
    )

    # Skill 3: generate the executive narrative
    narrative = run_skill(
        "executive_writer",
        f"Write a 300-word executive summary for the board. Revenue data: {json.dumps(revenue_data)}. "
        f"Risk data: {json.dumps(risk_data)}.",
        FILE_TOOLS
    )

    return narrative
```

---

## Skills vs. Tools vs. Agents

| Concept | Scope | Has its own loop? | Stateful? |
|---|---|---|---|
| **Tool** | Single function call (search, SQL query) | No | No |
| **Skill** | Multi-step workflow with a defined purpose | Yes | Session only |
| **Agent** | Open-ended goal, may use many skills | Yes | Yes (long-term memory) |

A tool is a leaf action. A skill is a composed workflow. An agent orchestrates skills and tools to pursue a goal.

---

## Enterprise Skill Library

For an enterprise deployment, build and version a shared skill library:

```
skills/
├── data/
│   ├── revenue_analysis.py
│   ├── churn_prediction.py
│   └── anomaly_detection.py
├── communication/
│   ├── executive_writer.py
│   ├── email_drafter.py
│   └── slack_reporter.py
├── engineering/
│   ├── code_reviewer.py
│   ├── pr_summariser.py
│   └── incident_analyser.py
└── compliance/
    ├── pii_detector.py
    ├── policy_checker.py
    └── audit_logger.py
```

Each skill file exports:
- The `Skill` object (system prompt, tools, output schema)
- A `run(task, context)` convenience function
- Unit tests for the skill's output schema validation
- Cost and latency benchmarks

---

## Next

→ [Concept 05 — Enterprise Patterns: HITL, Approval Workflows, Multi-Tenancy](./05-enterprise-patterns.md)
