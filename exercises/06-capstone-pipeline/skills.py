# skills.py
import json
import os
from typing import Any, Callable

import anthropic
from dotenv import load_dotenv

from observability import write_log_event

load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Sonnet for skills: they require stronger synthesis than workers.
SKILLS_MODEL = "claude-sonnet-4-6"

# ── Skill implementations ─────────────────────────────────────────

def _generate_executive_summary(run_id: str, research_data: dict) -> dict:
    """
    Synthesize news + sentiment + financial data into an executive brief.
    Returns a dict with: headline, situation, opportunity, watch_items, verdict.
    """
    prompt = f"""\
You are a senior investment analyst writing an executive brief for a portfolio committee.

Given the research data below, produce a JSON object with EXACTLY these fields:
  - headline:    one compelling sentence, max 15 words
  - situation:   2 sentences describing the current state of play
  - opportunity: 1 sentence on the primary upside case
  - watch_items: list of 2-3 risks or factors to monitor
  - verdict:     exactly one of "Favorable" | "Neutral" | "Cautious"

Research data:
{json.dumps(research_data, indent=2)}

Return ONLY valid JSON. No markdown fences, no explanation.
"""

    response = client.messages.create(
        model=SKILLS_MODEL,
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )

    write_log_event("skill_invoke", {
        "run_id":        run_id,
        "skill":         "generate_executive_summary",
        "input_tokens":  response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    })

    text = _strip_fences(response.content[0].text)
    return json.loads(text)


def _classify_risk(run_id: str, research_data: dict) -> dict:
    """
    Classify investment risk level from aggregated research.
    Returns: risk_score, risk_level, primary_risk_factors, mitigating_factors.
    """
    prompt = f"""\
You are a risk management expert advising an investment committee.

Analyze the research data below and return a JSON object with EXACTLY these fields:
  - risk_score:            float from 0.0 (no risk) to 1.0 (extreme risk)
  - risk_level:            exactly one of "Low" | "Medium" | "High" | "Critical"
  - primary_risk_factors:  list of top 3 risk factors (short phrases)
  - mitigating_factors:    list of 2-3 factors that reduce risk (short phrases)

Risk level guidance:
  0.0–0.35 → Low   |   0.35–0.60 → Medium   |   0.60–0.80 → High   |   0.80+ → Critical

Research data:
{json.dumps(research_data, indent=2)}

Return ONLY valid JSON.
"""

    response = client.messages.create(
        model=SKILLS_MODEL,
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )

    write_log_event("skill_invoke", {
        "run_id":        run_id,
        "skill":         "classify_risk",
        "input_tokens":  response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    })

    text = _strip_fences(response.content[0].text)
    return json.loads(text)


def _strip_fences(text: str) -> str:
    """Remove markdown code fences if the model wraps its JSON output."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Drop first line (```json or ```) and last line (```)
        text = "\n".join(lines[1:-1])
    return text.strip()

# ── Registry ──────────────────────────────────────────────────────

SKILL_REGISTRY: dict[str, Callable] = {
    "generate_executive_summary": _generate_executive_summary,
    "classify_risk":              _classify_risk,
}


def invoke_skill(skill_name: str, run_id: str, **kwargs) -> Any:
    """
    Look up and call a skill by name.

    Usage:
        result = invoke_skill("classify_risk", run_id=run_id, research_data={...})
    """
    fn = SKILL_REGISTRY.get(skill_name)
    if fn is None:
        available = list(SKILL_REGISTRY)
        raise ValueError(f"Unknown skill {skill_name!r}. Available: {available}")
    return fn(run_id=run_id, **kwargs)