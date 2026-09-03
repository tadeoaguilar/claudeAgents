import json
import os
import sys
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

load_dotenv()

from observability import PipelineTracer, write_log_event
from agents import NewsAgent, SentimentAgent, FinancialsAgent
from skills import invoke_skill
from hitl import ApprovalRequest, hitl_gate

RISK_THRESHOLD = 0.70   # Scores above this trigger HITL
console = Console()

# ── Orchestrator ──────────────────────────────────────────────────

class Orchestrator:
    """
    Owns the tracer and coordinates the full research pipeline:
    1. Dispatch three worker agents in sequence.
    2. Apply two skills to synthesize the results.
    3. Run HITL gate if risk score exceeds threshold.
    4. Assemble and save the final report.
    """

    def __init__(self, run_id: str):
        self.run_id  = run_id
        self.tracer  = PipelineTracer(run_id)

    def run_pipeline(self, query: str) -> dict:
        pipeline_start = time.time()

        write_log_event("pipeline_start", {"run_id": self.run_id, "query": query})

        console.print(Panel(
            f"[bold cyan]Market Research Intelligence Pipeline[/bold cyan]\n"
            f"Query : [yellow]{query}[/yellow]\n"
            f"Run ID: {self.run_id}",
            expand=False,
        ))

        # ── Stage 1: Worker agents ─────────────────────────────────
        console.print("\n[bold]Stage 1 — Gathering intelligence[/bold]")

        orch_span = self.tracer.span("orchestrator")

        news_result      = self._run_agent(NewsAgent,      query,                                       orch_span.span_id)
        sentiment_result = self._run_agent(SentimentAgent, f"Analyze market sentiment for: {query}",   orch_span.span_id)
        financials_result= self._run_agent(FinancialsAgent,f"Get financial signals for: {query}",      orch_span.span_id)

        # ── Stage 2: Aggregate ─────────────────────────────────────
        research_data = {
            "query":      query,
            "news":       news_result["result"],
            "sentiment":  sentiment_result["result"],
            "financials": financials_result["result"],
        }

        # ── Stage 3: Skills ────────────────────────────────────────
        console.print("\n[bold]Stage 2 — Applying skills[/bold]")

        summary = invoke_skill(
            "generate_executive_summary",
            run_id=self.run_id,
            research_data=research_data,
        )
        console.print(
            f"  [green]✓[/green] executive_summary — "
            f"verdict: [bold]{summary.get('verdict', '?')}[/bold] | "
            f"headline: [italic]{summary.get('headline', '')[:60]}[/italic]"
        )

        risk = invoke_skill(
            "classify_risk",
            run_id=self.run_id,
            research_data=research_data,
        )
        risk_score = risk.get("risk_score", 0.0)
        console.print(
            f"  [green]✓[/green] classify_risk — "
            f"level: [bold]{risk.get('risk_level', '?')}[/bold] | "
            f"score: {risk_score:.2f}"
        )

        # ── Stage 4: HITL gate (conditional) ──────────────────────
        if risk_score > RISK_THRESHOLD:
            console.print(
                f"\n[bold yellow]Stage 3 — HITL gate[/bold yellow] "
                f"(risk {risk_score:.2f} > threshold {RISK_THRESHOLD})"
            )
            approved = hitl_gate(ApprovalRequest(
                run_id=self.run_id,
                reason=f"Risk score {risk_score:.2f} exceeds threshold {RISK_THRESHOLD}",
                risk_score=risk_score,
                risk_level=risk.get("risk_level", "Unknown"),
                summary_headline=summary.get("headline", ""),
            ))
            if not approved:
                write_log_event("pipeline_end", {
                    "run_id": self.run_id,
                    "status": "rejected",
                    "elapsed_ms": (time.time() - pipeline_start) * 1000,
                })
                return {"status": "rejected", "run_id": self.run_id}

        # ── Stage 5: Assemble and deliver ─────────────────────────
        report = _assemble_report(
            query=query,
            run_id=self.run_id,
            summary=summary,
            risk=risk,
        )

        elapsed = time.time() - pipeline_start

        write_log_event("pipeline_end", {
            "run_id":              self.run_id,
            "status":              "delivered",
            "elapsed_ms":          elapsed * 1000,
            "total_input_tokens":  self.tracer.total_usage.input_tokens,
            "total_output_tokens": self.tracer.total_usage.output_tokens,
            "total_cost_usd":      self.tracer.total_usage.total_cost(),
            "risk_score":          risk_score,
            "verdict":             summary.get("verdict", "Unknown"),
        })

        return {
            "status":        "delivered",
            "report":        report,
            "run_id":        self.run_id,
            "elapsed_s":     elapsed,
            "total_cost_usd": self.tracer.total_usage.total_cost(),
        }

    def _run_agent(self, AgentClass, task: str, parent_span_id: str) -> dict:
        agent  = AgentClass(tracer=self.tracer, parent_span_id=parent_span_id)
        console.print(f"  Running [cyan]{agent.name}[/cyan]...")
        result = agent.run(task)
        console.print(
            f"  [green]✓[/green] {agent.name} — "
            f"{result['elapsed_ms']:.0f} ms | "
            f"{result['usage'].input_tokens + result['usage'].output_tokens} tokens | "
            f"${result['usage'].total_cost():.4f}"
        )
        return result


# ── Report assembly ───────────────────────────────────────────────

def _assemble_report(query: str, run_id: str, summary: dict, risk: dict) -> str:
    verdict_icon = {"Favorable": "🟢", "Neutral": "🟡", "Cautious": "🔴"}.get(summary.get("verdict", ""), "⚪")
    risk_icon    = {"Low": "🟢", "Medium": "🟡", "High": "🟠", "Critical": "🔴"}.get(risk.get("risk_level", ""), "⚪")

    watch_items   = "\n".join(f"- {w}" for w in summary.get("watch_items", []))
    risk_factors  = "\n".join(f"- {r}" for r in risk.get("primary_risk_factors", []))
    mitigators    = "\n".join(f"- {m}" for m in risk.get("mitigating_factors", []))

    return f"""\
# Market Intelligence Report

**Query:** {query}
**Run ID:** {run_id}

---

## Executive Summary

**Headline:** {summary.get('headline', '')}
**Verdict:** {verdict_icon} {summary.get('verdict', '')}

{summary.get('situation', '')}

{summary.get('opportunity', '')}

### Items to Watch
{watch_items}

---

## Risk Assessment

**Risk Level:** {risk_icon} {risk.get('risk_level', '')} (score: {risk.get('risk_score', 0):.2f})

### Primary Risk Factors
{risk_factors}

### Mitigating Factors
{mitigators}

---
*Generated by Market Research Intelligence Pipeline — Run {run_id}*
"""


# ── Entry point ───────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: python pipeline.py "<company or topic>"')
        sys.exit(1)

    query  =  " ".join(sys.argv[1:])
    run_id = uuid.uuid4().hex[:12]

    result = Orchestrator(run_id=run_id).run_pipeline(query)

    if result["status"] == "rejected":
        console.print("\n[bold red]Pipeline halted — report rejected at HITL gate.[/bold red]")
        return

    # Print report
    console.print("\n" + result["report"])

    # Save report
    report_path = Path(f"report_{run_id}.md")
    report_path.write_text(result["report"])

    # Summary table
    table = Table(title="Pipeline Summary", show_header=True, header_style="bold cyan")
    table.add_column("Metric",  style="cyan",  no_wrap=True)
    table.add_column("Value",   style="white")
    table.add_row("Run ID",     run_id)
    table.add_row("Total time", f"{result['elapsed_s']:.1f} s")
    table.add_row("Total cost", f"${result['total_cost_usd']:.4f}")
    table.add_row("Report",     str(report_path))
    console.print(table)


if __name__ == "__main__":
    main()