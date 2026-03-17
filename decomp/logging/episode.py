"""Structured episode logging for RL training data collection.

Each decompilation attempt is an "episode" consisting of steps.
Episodes are saved as JSON files for future training pipelines.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class ToolCall:
    """A single tool invocation within a step."""

    name: str
    input: dict
    output: str
    duration_ms: int = 0


@dataclass
class Step:
    """One turn of the agent loop: assistant message + tool calls + results."""

    step_number: int
    timestamp: str
    assistant_text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    match_percent: float | None = None
    compiled: bool | None = None
    token_usage: dict | None = None


@dataclass
class Episode:
    """A complete decompilation episode for one function."""

    function_name: str
    project: str
    model: str
    start_time: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    end_time: str | None = None
    steps: list[Step] = field(default_factory=list)
    outcome: str = "incomplete"  # "match", "partial", "failed", "incomplete"
    final_match_percent: float = 0.0
    best_match_percent: float = 0.0
    total_tokens: int = 0
    instruction_count: int = 0
    initial_m2c_source: str | None = None
    final_source: str | None = None

    def add_step(self, step: Step) -> None:
        self.steps.append(step)
        if step.match_percent is not None:
            if step.match_percent > self.best_match_percent:
                self.best_match_percent = step.match_percent
            self.final_match_percent = step.match_percent
        if step.token_usage:
            self.total_tokens += step.token_usage.get("input_tokens", 0)
            self.total_tokens += step.token_usage.get("output_tokens", 0)

    def finish(self, outcome: str) -> None:
        self.outcome = outcome
        self.end_time = datetime.now(timezone.utc).isoformat()

    def save(self, log_dir: Path) -> Path:
        """Save episode as JSON. Returns the path to the saved file."""
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"{ts}_{self.function_name}.json"
        path = log_dir / filename
        path.write_text(json.dumps(asdict(self), indent=2))
        return path


class EpisodeLogger:
    """Manages episode creation and step tracking."""

    def __init__(
        self,
        function_name: str,
        project: str,
        model: str,
        instruction_count: int = 0,
    ) -> None:
        self.episode = Episode(
            function_name=function_name,
            project=project,
            model=model,
            instruction_count=instruction_count,
        )
        self._step_count = 0

    def begin_step(self) -> int:
        self._step_count += 1
        return self._step_count

    def record_step(
        self,
        step_number: int,
        *,
        assistant_text: str | None = None,
        tool_calls: list[ToolCall] | None = None,
        match_percent: float | None = None,
        compiled: bool | None = None,
        token_usage: dict | None = None,
    ) -> Step:
        step = Step(
            step_number=step_number,
            timestamp=datetime.now(timezone.utc).isoformat(),
            assistant_text=assistant_text,
            tool_calls=tool_calls or [],
            match_percent=match_percent,
            compiled=compiled,
            token_usage=token_usage,
        )
        self.episode.add_step(step)
        return step

    def finish(self, outcome: str, log_dir: Path) -> Path:
        self.episode.finish(outcome)
        return self.episode.save(log_dir)
