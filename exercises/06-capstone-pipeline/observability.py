import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

LOG_FILE = Path(os.getenv("PIPELINE_LOG_FILE", str(Path(__file__).parent / "pipeline_runs.jsonl")))


# ---- To Observe Span
@dataclass
class SpanContext:
    run_id: str
    agent_name: str
    span_id: str = field(default_factory=lambda: str(uuid.uuid4().hex[:8]))
    parent_span_id: Optional[str] = None
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None 

    def elapsed_ms(self) -> float:
        if self.end_time is None:
            return 0.0
        return (self.end_time - self.start_time) * 1000

# ---- To Observe Token usage + cost

@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    # Sonnet 4.6 pricing per 1 M tokens (update if you change MODEL)
    _INPUT_PRICE   = 3.00
    _OUTPUT_PRICE  = 15.00
    _CR_PRICE      = 0.30
    _CW_PRICE      = 3.75

    def total_cost(self) -> float:
        return (
            (self.input_tokens / 1_000_000) * self._INPUT_PRICE +
            (self.output_tokens / 1_000_000) * self._OUTPUT_PRICE +
            (self.cache_read_tokens / 1_000_000) * self._CR_PRICE +
            (self.cache_write_tokens / 1_000_000) * self._CW_PRICE
        )

# ---- Tracer

class PipelineTracer:
    """One instance of a pipeline run. Acumulates cost across all agents."""
    def __init__(self, run_id: str ):
        self.run_id = run_id
        self.total_usage = TokenUsage()
    def span(self, agent_name: str, parent_span_id: Optional[str] = None) -> SpanContext:
        return SpanContext(run_id=self.run_id, agent_name=agent_name, parent_span_id=parent_span_id)

    def record_usage(self, usage: TokenUsage) -> None:
        self.total_usage.input_tokens += usage.input_tokens
        self.total_usage.output_tokens += usage.output_tokens
        self.total_usage.cache_read_tokens += usage.cache_read_tokens
        self.total_usage.cache_write_tokens += usage.cache_write_tokens

def write_log_event(event_type: str, data: dict) -> None:
    """Write a log event to the log file in JSONL format."""
    event = {
        "timestamp": time.time(),
        "event_type": event_type,        
        **data
        }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(event) + "\n")