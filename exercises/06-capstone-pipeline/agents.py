# agents.py
import json
import time
from typing import Optional
import anthropic
import os
from dotenv import load_dotenv
from observability import PipelineTracer, TokenUsage, write_log_event
from tools import TOOLS, execute_tool

load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


# Use Haiku for workers: faster and ~10× cheaper than Sonnet.
# Swap to "claude-sonnet-4-6" if you need stronger reasoning.
MODEL = "claude-haiku-4-5-20251001"

# ── Base agent ────────────────────────────────────────────────────

class AgentWorker:
    """
    Runs a single-agent agentic loop with built-in observability.

    Subclasses override:
      - name          (str)  — used in log events
      - system_prompt (str)  — the agent's role and output format
      - allowed_tools (list) — tool names this agent may call
    """

    name:           str       = "base_agent"
    system_prompt:  str       = "You are a helpful assistant."
    allowed_tools:  list[str] = []

    MAX_ITERATIONS = 10
    TOKEN_BUDGET = 6_000  # trim conversation when input tokens exceed this limit


    def __init__(self, tracer: PipelineTracer, parent_span_id: Optional[str] = None):
        self.tracer         = tracer
        self.parent_span_id = parent_span_id

    # ── Public ────────────────────────────────────────────────────

    def run(self, task: str) -> dict:
        """Execute the task and return a result dict."""
        span  = self.tracer.span(self.name, parent_span_id=self.parent_span_id)
        usage = TokenUsage()

        write_log_event("agent_start", {
            "run_id":       span.run_id,
            "span_id":      span.span_id,
            "parent_span":  span.parent_span_id,
            "agent":        self.name,
            "task_preview": task[:120],
        })

        messages    = [{"role": "user", "content": task}]
        result_text = ""
        iterations  = 0

        while iterations < self.MAX_ITERATIONS:
            iterations += 1

            response = client.messages.create(
                model=MODEL,
                max_tokens=2048,
                system=self.system_prompt,
                tools=self._active_tools(),
                messages=messages,
            )

            usage.input_tokens  += response.usage.input_tokens
            usage.output_tokens += response.usage.output_tokens

            # Trim context if the conversation history is getting too large
            messages = self._trim_context(
                messages,
                last_input_tokens=response.usage.input_tokens,
                run_id=span.run_id,
            )

            if response.stop_reason == "end_turn":
                result_text = next(
                    (b.text for b in response.content if hasattr(b, "text")), ""
                )
                break

            if response.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": response.content})
                tool_results = []

                for block in response.content:
                    if block.type != "tool_use":
                        continue

                    raw_result = execute_tool(block.name, block.input)

                    write_log_event("tool_call", {
                        "run_id":  span.run_id,
                        "span_id": span.span_id,
                        "agent":   self.name,
                        "tool":    block.name,
                        "input":   block.input,
                    })

                    tool_results.append({
                        "type":        "tool_result",
                        "tool_use_id": block.id,
                        "content":     json.dumps(raw_result),
                    })

                messages.append({"role": "user", "content": tool_results})

        span.end_time = time.time()
        self.tracer.record_usage(usage)

        write_log_event("agent_end", {
            "run_id":        span.run_id,
            "span_id":       span.span_id,
            "agent":         self.name,
            "elapsed_ms":    span.elapsed_ms(),
            "iterations":    iterations,
            "input_tokens":  usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cost_usd":      usage.total_cost(),
        })

        return {
            "agent":      self.name,
            "result":     result_text,
            "usage":      usage,
            "elapsed_ms": span.elapsed_ms(),
        }

    # ── Private ───────────────────────────────────────────────────

    def _active_tools(self) -> list[dict]:
        """Return only the tool schemas this agent is allowed to use."""
        return [t for t in TOOLS if t["name"] in self.allowed_tools]

    def _trim_context(
        self,
        messages: list,
        last_input_tokens: int,
        run_id: str,
    ) -> list:
        """
        If the conversation is growing past TOKEN_BUDGET, collapse the
        middle turns into a single summary to prevent unbounded context growth.

        Invariants kept:
          - messages[0]  = original user task (always kept verbatim)
          - messages[-2:] = last assistant turn + tool results (required by API)
          - everything in between is summarised and discarded
        """
        if last_input_tokens < self.TOKEN_BUDGET:
            return messages

        # Need at least: task + one middle turn + last two turns to bother trimming
        if len(messages) < 5:
            return messages

        original_task = messages[0]
        last_two      = messages[-2:]
        to_summarise  = messages[1:-2]

        summary = self._summarise_history(to_summarise)

        write_log_event("context_trimmed", {
            "run_id":           run_id,
            "agent":            self.name,
            "tokens_before":    last_input_tokens,
            "turns_collapsed":  len(to_summarise),
        })

        return [
            original_task,
            {
                "role":    "user",
                "content": f"[Summary of prior research]\n{summary}",
            },
            *last_two,
        ]

    def _summarise_history(self, messages: list) -> str:
        """
        Ask Claude (Haiku, small token budget) to compress prior turns
        into a concise bullet-point summary the agent can reason from.
        """
        history_text = "\n".join(
            f"{m['role'].upper()}: {str(m['content'])[:600]}"
            for m in messages
        )
        response = client.messages.create(
            model=MODEL,
            max_tokens=300,
            messages=[{
                "role":    "user",
                "content": (
                    "Summarise the key findings from these agent conversation turns "
                    "in 4-6 bullet points. Include: data already retrieved, "
                    "tool results, and any decisions made. Be concise.\n\n"
                    + history_text
                ),
            }],
        )
        return response.content[0].text
# ── Worker specializations ────────────────────────────────────────

class NewsAgent(AgentWorker):
    name = "news_agent"
    system_prompt = """\
You are a financial news research specialist.

TASK: Search for recent news about the given topic, filter to the last 60 days,
and return a JSON object with exactly these fields:
  - key_events: list of the 3 most important news items, each with:
      { "title": str, "date": str, "source": str, "impact": "positive"|"negative"|"neutral" }
  - overall_narrative: one paragraph (2-3 sentences) summarizing the news landscape

PROCESS:
1. Call search_news to fetch articles.
2. Call filter_by_date with days_back=60 to focus on recent ones.
3. Analyze the filtered articles.
4. Return the JSON object described above. No markdown, no explanation — just JSON.
"""
    allowed_tools = ["search_news", "filter_by_date"]


class SentimentAgent(AgentWorker):
    name = "sentiment_agent"
    system_prompt = """\
You are a market sentiment analyst.

TASK: Analyze market and social sentiment for the given topic and return a JSON object with:
  - sentiment_score: float 0.0 (very bearish) to 1.0 (very bullish)
  - sentiment_label: "bullish" | "neutral" | "bearish"
  - social_momentum: one sentence describing social media activity
  - key_signals: list of 2-3 specific data points that drove your assessment

PROCESS:
1. Call analyze_sentiment with relevant text snippets about the topic.
2. Call get_social_metrics for the topic.
3. Combine both signals into the JSON object above. JSON only — no extra text.
"""
    allowed_tools = ["analyze_sentiment", "get_social_metrics"]


class FinancialsAgent(AgentWorker):
    name = "financials_agent"
    system_prompt = """\
You are a quantitative financial analyst.

TASK: Retrieve and interpret financial signals for the given company and return a JSON object with:
  - financial_health: "strong" | "stable" | "weak"
  - price_momentum:   one sentence on recent price action
  - analyst_view:     one sentence summarizing analyst consensus
  - key_metrics:      dict with the most important numbers from the data

PROCESS:
1. Call get_financial_signals with a 90-day period.
2. Interpret the numbers.
3. Return the JSON object above. JSON only.
"""
    allowed_tools = ["get_financial_signals"]