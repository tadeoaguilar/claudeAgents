# summarize_run.py
#!/usr/bin/env python3
"""Parse pipeline_runs.jsonl and print a cost + latency report."""
import json
import sys
from collections import defaultdict
from pathlib import Path

LOG_FILE = Path("pipeline_runs.jsonl")

def main():
    if not LOG_FILE.exists():
        print("No pipeline_runs.jsonl found. Run the pipeline first.")
        return

    events = [json.loads(line) for line in LOG_FILE.read_text().splitlines() if line.strip()]

    # Group events by run_id
    runs: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        if rid := e.get("run_id"):
            runs[rid].append(e)

    print(f"\n{'RUN ID':<14} {'STATUS':<10} {'TIME(s)':<9} {'COST($)':<10} {'IN TOK':<8} {'OUT TOK':<8} {'RISK'}")
    print("-" * 72)

    for run_id, evts in runs.items():
        end = next((e for e in evts if e["event_type"] == "pipeline_end"), None)
        if not end:
            continue
        print(
            f"{run_id:<14} "
            f"{end.get('status','?'):<10} "
            f"{end.get('elapsed_ms', 0)/1000:<9.1f} "
            f"{end.get('total_cost_usd', 0):<10.4f} "
            f"{end.get('total_input_tokens', 0):<8} "
            f"{end.get('total_output_tokens', 0):<8} "
            f"{end.get('risk_score', '?')}"
        )

    # Per-agent latency for the most recent run
    latest_run_id = list(runs.keys())[-1]
    print(f"\nPer-agent breakdown for run {latest_run_id}:")
    print(f"  {'AGENT':<22} {'ELAPSED(ms)':<14} {'INPUT':<8} {'OUTPUT':<8} {'COST($)'}")
    print("  " + "-" * 60)
    for e in runs[latest_run_id]:
        if e["event_type"] == "agent_end":
            print(
                f"  {e['agent']:<22} "
                f"{e.get('elapsed_ms', 0):<14.0f} "
                f"{e.get('input_tokens', 0):<8} "
                f"{e.get('output_tokens', 0):<8} "
                f"{e.get('cost_usd', 0):.4f}"
            )


if __name__ == "__main__":
    main()