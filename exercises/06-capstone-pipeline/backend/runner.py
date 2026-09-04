import asyncio
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from state import registry

PIPELINE_DIR = str(Path(__file__).parent.parent)
DATA_DIR = Path(os.getenv("DATA_DIR", PIPELINE_DIR))
_executor = ThreadPoolExecutor(max_workers=4)


def _make_web_hitl_gate(run_id: str):
    """Returns a hitl_gate replacement that uses the web registry."""
    def web_hitl_gate(request, event_registry=None):
        # Always use registry when called from runner
        from hitl import hitl_gate as original_hitl_gate
        return original_hitl_gate(request, event_registry=registry)
    return web_hitl_gate


def _run_pipeline_sync(run_id: str, query: str) -> None:
    if PIPELINE_DIR not in sys.path:
        sys.path.insert(0, PIPELINE_DIR)

    registry.update_status(run_id, "running")
    registry.append_event(run_id, "stage_start", {"stage": 1, "label": "Gathering intelligence"})

    try:
        import importlib
        # Reload modules to avoid stale state from previous runs in same process
        import pipeline as pipeline_module
        import hitl as hitl_module

        from pipeline import Orchestrator

        # Patch hitl_gate in pipeline module namespace to use web registry
        def web_hitl_gate(request, event_registry=None):
            return hitl_module.hitl_gate(request, event_registry=registry)

        pipeline_module.hitl_gate = web_hitl_gate

        # Wrap agent execution to emit SSE events per agent
        original_run_agent = Orchestrator._run_agent

        agent_names = []

        def patched_run_agent(self, AgentClass, task, parent_span_id):
            result = original_run_agent(self, AgentClass, task, parent_span_id)
            import agents as agents_module
            agent_map = {
                agents_module.NewsAgent: "news_agent",
                agents_module.SentimentAgent: "sentiment_agent",
                agents_module.FinancialsAgent: "financials_agent",
            }
            name = agent_map.get(AgentClass, AgentClass.__name__)
            registry.append_event(run_id, "agent_complete", {
                "agent": name,
                "elapsed_ms": result.get("elapsed_ms", 0),
                "cost_usd": result["usage"].total_cost() if result.get("usage") else 0,
            })
            return result

        Orchestrator._run_agent = patched_run_agent

        orchestrator = Orchestrator(run_id=run_id)

        # Intercept skill invocations to emit SSE events
        import skills as skills_module
        original_invoke_skill = skills_module.invoke_skill

        skills_called = []

        def patched_invoke_skill(skill_name, run_id=run_id, **kwargs):
            result = original_invoke_skill(skill_name, run_id=run_id, **kwargs)
            skills_called.append(skill_name)
            if len(skills_called) == 1:
                registry.append_event(run_id, "stage_start", {"stage": 2, "label": "Applying skills"})
            registry.append_event(run_id, "skill_complete", {"skill": skill_name})
            return result

        pipeline_module.invoke_skill = patched_invoke_skill

        result = orchestrator.run_pipeline(query)

        # Restore patched methods
        Orchestrator._run_agent = original_run_agent
        pipeline_module.invoke_skill = original_invoke_skill
        pipeline_module.hitl_gate = hitl_module.hitl_gate

        if result["status"] == "rejected":
            registry.update_status(run_id, "rejected", finished_at=time.time())
            registry.append_event(run_id, "pipeline_error", {"reason": "Report rejected at HITL gate"})
            return

        report_text = result["report"]
        registry.update_status(
            run_id, "delivered",
            report=report_text,
            finished_at=time.time(),
        )

        # Save report file alongside pipeline files
        report_path = DATA_DIR / f"report_{run_id}.md"
        report_path.write_text(report_text)

        registry.append_event(run_id, "pipeline_complete", {
            "report_path": str(report_path),
            "elapsed_s": result.get("elapsed_s", 0),
            "total_cost_usd": result.get("total_cost_usd", 0),
        })

    except Exception as exc:
        registry.update_status(run_id, "error", error=str(exc), finished_at=time.time())
        registry.append_event(run_id, "pipeline_error", {"error": str(exc)})
        raise


async def launch_pipeline(run_id: str, query: str) -> None:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(_executor, _run_pipeline_sync, run_id, query)
