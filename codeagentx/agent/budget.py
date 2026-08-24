"""Run-level resource accounting and optional hard limits."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic
from typing import Any, Mapping

from codeagentx.config import Config


@dataclass
class RunBudget:
    """Tracks resource usage for one task run."""

    max_turns: int
    max_tool_calls: int | None = None
    max_run_seconds: float | None = None
    started_at: float = field(default_factory=monotonic)
    turns: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    exhausted_reason: str | None = None

    @classmethod
    def from_config(cls, config: Config) -> "RunBudget":
        max_tool_calls = getattr(config, "max_tool_calls", None)
        max_run_seconds = getattr(config, "max_run_seconds", None)
        return cls(
            max_turns=max(0, int(getattr(config, "max_turns", 0) or 0)),
            max_tool_calls=(
                max(0, int(max_tool_calls))
                if max_tool_calls is not None
                else None
            ),
            max_run_seconds=(
                max(0.0, float(max_run_seconds))
                if max_run_seconds is not None
                else None
            ),
        )

    def begin_turn(self) -> str | None:
        reason = self.limit_reason()
        if reason is not None:
            return reason
        self.turns += 1
        return None

    def record_tool_calls(self, count: int) -> None:
        self.tool_calls += max(0, int(count))

    def record_model_usage(self, usage: Mapping[str, Any] | None) -> None:
        if not isinstance(usage, Mapping):
            return
        self.input_tokens += _usage_int(
            usage,
            "input_tokens",
            "prompt_tokens",
        )
        self.output_tokens += _usage_int(
            usage,
            "output_tokens",
            "completion_tokens",
        )

    def mark_exhausted(self, reason: str) -> None:
        """Record the first hard-limit reason that ended the run."""

        if self.exhausted_reason is None:
            self.exhausted_reason = str(reason)

    def limit_reason(self) -> str | None:
        if (
            self.max_tool_calls is not None
            and self.tool_calls >= self.max_tool_calls
        ):
            return f"max tool calls reached ({self.max_tool_calls})"
        if (
            self.max_run_seconds is not None
            and self.elapsed_seconds >= self.max_run_seconds
        ):
            return f"max run time reached ({self.max_run_seconds:g}s)"
        return None

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0, monotonic() - self.started_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_turns": self.max_turns,
            "max_tool_calls": self.max_tool_calls,
            "max_run_seconds": self.max_run_seconds,
            "turns": self.turns,
            "tool_calls": self.tool_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.input_tokens + self.output_tokens,
            "elapsed_seconds": round(self.elapsed_seconds, 6),
            "exhausted": self.exhausted_reason is not None,
            "exhausted_reason": self.exhausted_reason,
        }


def _usage_int(usage: Mapping[str, Any], *keys: str) -> int:
    for key in keys:
        value = usage.get(key)
        if value is None:
            continue
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            continue
    return 0
