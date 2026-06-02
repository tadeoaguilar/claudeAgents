"""
Reads agent_runs.jsonl and prints a performance and cost summary.

Run AFTER monitored_agent.py:
    python summarise_logs.py
"""

import json
import os
import statistics
from collections import defaultdict

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()
LOG_FILE = "agent_runs.jsonl"

def load_events(path: str) -> list[dict]:
    if not os.path.exists(path):
        console.print(f"[red]Log file not found: {path}[/red]")
        console.print("Run monitored_agent.py first.")
        raise SystemExit(1)
    events = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events

def main():
    events = load_events(LOG_FILE)

    runs          = [e for e in events if e["event"] == "run_complete"]
    model_calls   = [e for e in events if e["event"] == "model_call"]
    tool_calls    = [e for e in events if e["event"] == "tool_call"]

    if not runs:
        console.print("[yellow]No completed runs found in log.[/yellow]")
        return

    # ── Overall summary ──
    total_runs      = len(runs)
    success_runs    = [r for r in runs if r.get("status") == "success"]
    success_rate    = len(success_runs) / total_runs * 100

    costs       = [r.get("total_cost_usd", 0) for r in success_runs]
    durations   = [r.get("duration_ms", 0) for r in success_runs]
    turn_counts = [r.get("turn_count", 0) for r in success_runs]

    console.print(Panel("[bold]Agent Run Summary[/bold]", expand=False))

    summary_table = Table(show_header=False, padding=(0, 2))
    summary_table.add_column("Metric",    style="cyan")
    summary_table.add_column("Value",     style="white")

    summary_table.add_row("Total runs",          str(total_runs))
    summary_table.add_row("Success rate",        f"{success_rate:.1f}%")
    summary_table.add_row("Avg cost per run",    f"${statistics.mean(costs):.5f}" if costs else "N/A")
    summary_table.add_row("Total cost",          f"${sum(costs):.4f}")
    summary_table.add_row("Avg duration",        f"{statistics.mean(durations):.0f}ms" if durations else "N/A")
    summary_table.add_row("Avg turns per run",   f"{statistics.mean(turn_counts):.1f}" if turn_counts else "N/A")

    console.print(summary_table)

    # ── Token and cache breakdown ──
    total_input   = sum(e.get("input_tokens", 0) for e in model_calls)
    total_output  = sum(e.get("output_tokens", 0) for e in model_calls)
    cache_reads   = sum(e.get("cache_read_tokens", 0) for e in model_calls)
    cache_writes  = sum(e.get("cache_write_tokens", 0) for e in model_calls)
    total_tokens  = total_input + total_output

    cache_hit_rate = (cache_reads / total_input * 100) if total_input > 0 else 0

    console.print("\n[bold]Token & Cache Breakdown[/bold]")
    token_table = Table(show_header=False, padding=(0, 2))
    token_table.add_column("Metric", style="cyan")
    token_table.add_column("Value",  style="white")
    token_table.add_row("Total input tokens",   f"{total_input:,}")
    token_table.add_row("Total output tokens",  f"{total_output:,}")
    token_table.add_row("Cache write tokens",   f"{cache_writes:,}")
    token_table.add_row("Cache read tokens",    f"{cache_reads:,}")
    token_table.add_row("Cache hit rate",       f"[green]{cache_hit_rate:.1f}%[/green]" if cache_hit_rate > 50 else f"[yellow]{cache_hit_rate:.1f}%[/yellow]")
    console.print(token_table)

    # ── Per-tool latency ──
    if tool_calls:
        console.print("\n[bold]Per-Tool Latency[/bold]")
        by_tool: dict[str, list[float]] = defaultdict(list)
        for tc in tool_calls:
            by_tool[tc["tool"]].append(tc.get("duration_ms", 0))

        tool_table = Table()
        tool_table.add_column("Tool",        style="cyan")
        tool_table.add_column("Calls",       justify="right")
        tool_table.add_column("Avg ms",      justify="right")
        tool_table.add_column("P95 ms",      justify="right")
        tool_table.add_column("Errors",      justify="right", style="red")

        error_counts: dict[str, int] = defaultdict(int)
        for tc in tool_calls:
            if tc.get("error"):
                error_counts[tc["tool"]] += 1

        for tool_name, latencies in sorted(by_tool.items()):
            sorted_l = sorted(latencies)
            p95 = sorted_l[int(len(sorted_l) * 0.95)] if len(sorted_l) > 1 else sorted_l[0]
            tool_table.add_row(
                tool_name,
                str(len(latencies)),
                f"{statistics.mean(latencies):.1f}",
                f"{p95:.1f}",
                str(error_counts.get(tool_name, 0)),
            )
        console.print(tool_table)

    # ── Per-run breakdown ──
    console.print("\n[bold]Per-Run Detail[/bold]")
    run_table = Table()
    run_table.add_column("Run ID",   style="dim")
    run_table.add_column("Company")
    run_table.add_column("Status")
    run_table.add_column("Turns",    justify="right")
    run_table.add_column("Tools",    justify="right")
    run_table.add_column("Cost $",   justify="right")
    run_table.add_column("ms",       justify="right")

    for r in runs:
        status = r.get("status", "?")
        color  = "green" if status == "success" else "red"
        run_table.add_row(
            r.get("run_id", "?"),
            r.get("company", "?"),
            f"[{color}]{status}[/{color}]",
            str(r.get("turn_count", "?")),
            str(r.get("total_tool_calls", "?")),
            f"${r.get('total_cost_usd', 0):.5f}",
            f"{r.get('duration_ms', 0):.0f}",
        )

    console.print(run_table)


if __name__ == "__main__":
    main()
