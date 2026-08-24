"""Retry policy driven by failure reflection reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from codeagentx.agent.state import utc_now_iso

from .strategy import RetryStrategyMatrix, RetryStrategyPlan


class ReflectionRetryStatus(Enum):
    RETRY = "retry"
    DISABLED = "disabled"
    EXHAUSTED = "exhausted"
    NON_RETRYABLE = "non_retryable"
    NO_REFLECTION = "no_reflection"


@dataclass(frozen=True)
class ReflectionRetryDecision:
    status: ReflectionRetryStatus
    reason: str
    retry_index: int
    max_retries: int
    reflection_summary: str = ""
    categories: list[str] = field(default_factory=list)
    prompt: str = ""
    strategy: Mapping[str, Any] | None = None
    created_at: str = field(default_factory=utc_now_iso)

    @property
    def should_retry(self) -> bool:
        return self.status == ReflectionRetryStatus.RETRY

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "reason": self.reason,
            "retry_index": self.retry_index,
            "max_retries": self.max_retries,
            "reflection_summary": self.reflection_summary,
            "categories": list(self.categories),
            "prompt": self.prompt,
            "strategy": dict(self.strategy) if self.strategy is not None else None,
            "created_at": self.created_at,
        }


class ReflectionRetryPolicy:
    """Convert reflection evidence into a bounded retry decision."""

    def __init__(
        self,
        *,
        max_prompt_chars: int = 6_000,
        enable_strategy_matrix: bool = True,
        strategy_matrix: RetryStrategyMatrix | None = None,
    ) -> None:
        self.max_prompt_chars = max_prompt_chars
        self.enable_strategy_matrix = enable_strategy_matrix
        self.strategy_matrix = strategy_matrix or RetryStrategyMatrix()

    def decide(
        self,
        reflection_report: Mapping[str, Any] | None,
        *,
        attempted_retries: int,
        max_retries: int,
        ranked_context_report: Mapping[str, Any] | None = None,
    ) -> ReflectionRetryDecision:
        if max_retries <= 0:
            return ReflectionRetryDecision(
                status=ReflectionRetryStatus.DISABLED,
                reason="reflection retry budget is disabled",
                retry_index=attempted_retries,
                max_retries=max_retries,
            )

        if not isinstance(reflection_report, Mapping):
            return ReflectionRetryDecision(
                status=ReflectionRetryStatus.NO_REFLECTION,
                reason="no reflection report is available",
                retry_index=attempted_retries,
                max_retries=max_retries,
            )

        summary = str(reflection_report.get("summary", "") or "")
        categories = _categories(reflection_report)
        strategy_plan = self._strategy_plan(
            reflection_report,
            ranked_context_report=ranked_context_report,
        )
        strategy_dict = strategy_plan.to_dict() if strategy_plan is not None else None

        if not bool(reflection_report.get("retryable", False)):
            return ReflectionRetryDecision(
                status=ReflectionRetryStatus.NON_RETRYABLE,
                reason="reflection report marked the failure as non-retryable",
                retry_index=attempted_retries,
                max_retries=max_retries,
                reflection_summary=summary,
                categories=categories,
                strategy=strategy_dict,
            )

        if strategy_plan is not None and not strategy_plan.should_retry:
            return ReflectionRetryDecision(
                status=ReflectionRetryStatus.NON_RETRYABLE,
                reason=f"retry strategy stopped automatic retry: {strategy_plan.strategy.value}",
                retry_index=attempted_retries,
                max_retries=max_retries,
                reflection_summary=summary,
                categories=categories,
                strategy=strategy_dict,
            )

        if attempted_retries >= max_retries:
            return ReflectionRetryDecision(
                status=ReflectionRetryStatus.EXHAUSTED,
                reason="reflection retry budget exhausted",
                retry_index=attempted_retries,
                max_retries=max_retries,
                reflection_summary=summary,
                categories=categories,
                strategy=strategy_dict,
            )

        retry_index = attempted_retries + 1
        prompt = self._build_prompt(
            reflection_report,
            retry_index=retry_index,
            max_retries=max_retries,
            ranked_context_report=ranked_context_report,
            strategy_plan=strategy_plan,
        )
        return ReflectionRetryDecision(
            status=ReflectionRetryStatus.RETRY,
            reason="reflection report is retryable and budget remains",
            retry_index=retry_index,
            max_retries=max_retries,
            reflection_summary=summary,
            categories=categories,
            prompt=prompt,
            strategy=strategy_dict,
        )

    def _build_prompt(
        self,
        reflection_report: Mapping[str, Any],
        *,
        retry_index: int,
        max_retries: int,
        ranked_context_report: Mapping[str, Any] | None = None,
        strategy_plan: RetryStrategyPlan | None = None,
    ) -> str:
        lines = [
            "The previous attempt failed verification and is eligible for a bounded retry.",
            f"Retry budget: attempt {retry_index}/{max_retries}.",
            f"Reflection summary: {reflection_report.get('summary', '')}",
        ]

        categories = _categories(reflection_report)
        if categories:
            lines.append("Failure categories: " + ", ".join(categories))

        if strategy_plan is not None:
            lines.append(f"Retry strategy: {strategy_plan.strategy.value}")
            if strategy_plan.actions:
                lines.append("Strategy actions:")
                lines.extend(f"- {item}" for item in strategy_plan.actions[:8])
            if strategy_plan.prompt_instructions:
                lines.append("Strategy instructions:")
                lines.extend(f"- {item}" for item in strategy_plan.prompt_instructions[:8])

        recommendations = reflection_report.get("recommendations", [])
        if isinstance(recommendations, list) and recommendations:
            lines.append("Recommendations:")
            lines.extend(f"- {item}" for item in recommendations[:6])

        signals = reflection_report.get("signals", [])
        if isinstance(signals, list) and signals:
            lines.append("Failure signals:")
            for signal in signals[:6]:
                if not isinstance(signal, Mapping):
                    continue
                category = signal.get("category", "unknown")
                severity = signal.get("severity", "warning")
                message = signal.get("message", "")
                evidence = _compact_evidence(signal.get("evidence", {}))
                lines.append(f"- [{severity}] {category}: {message}")
                if evidence:
                    lines.append(f"  evidence: {evidence}")

        context_lines = _ranked_context_lines(ranked_context_report)
        if context_lines:
            lines.append("Ranked context to inspect first:")
            lines.extend(context_lines)

        lines.extend([
            "Continue the same task. Use tools as needed, focus on the evidence above,",
            "avoid repeating failed actions, and finish with a concise final response after the fix.",
        ])

        prompt = "\n".join(str(line) for line in lines)
        return _truncate(prompt, self.max_prompt_chars)

    def _strategy_plan(
        self,
        reflection_report: Mapping[str, Any],
        *,
        ranked_context_report: Mapping[str, Any] | None,
    ) -> RetryStrategyPlan | None:
        if not self.enable_strategy_matrix:
            return None
        return self.strategy_matrix.decide(
            reflection_report,
            ranked_context_report=ranked_context_report,
        )


def _categories(reflection_report: Mapping[str, Any]) -> list[str]:
    signals = reflection_report.get("signals", [])
    categories: list[str] = []
    if not isinstance(signals, list):
        return categories

    for signal in signals:
        if not isinstance(signal, Mapping):
            continue
        category = signal.get("category")
        if category is not None:
            categories.append(str(category))
    return categories


def _compact_evidence(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""

    pieces: list[str] = []
    for key in (
        "command",
        "exit_code",
        "sandbox_status",
        "timed_out",
        "violation",
        "framework",
        "total",
        "failed",
        "errors",
        "failure_names",
        "tool_name",
        "count",
        "changed_files",
        "patch_count",
        "total_changed_lines",
        "critical",
        "deterministic",
        "violation_count",
        "changed_paths",
        "violations",
    ):
        item = value.get(key)
        if item in (None, "", [], {}):
            continue
        pieces.append(f"{key}={item!r}")
    return "; ".join(pieces)


def _ranked_context_lines(report: Mapping[str, Any] | None, *, limit: int = 6) -> list[str]:
    if not isinstance(report, Mapping):
        return []
    candidates = report.get("candidates", [])
    if not isinstance(candidates, list) or not candidates:
        return []

    lines: list[str] = []
    for candidate in candidates[:limit]:
        if not isinstance(candidate, Mapping):
            continue
        path = candidate.get("path", "")
        line = candidate.get("line", 0)
        score = candidate.get("score", 0)
        symbol = candidate.get("symbol_name") or candidate.get("kind") or "context"
        sources = ",".join(str(item) for item in candidate.get("sources", []) or [])
        reasons = "; ".join(str(item) for item in candidate.get("reasons", [])[:3])
        lines.append(f"- {path}:{line} {symbol} [score={score}; sources={sources}]")
        if reasons:
            lines.append(f"  reasons: {reasons}")
    return lines


def _truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    omitted = len(value) - max_chars
    return value[:max_chars] + f"\n... retry prompt truncated {omitted} chars"
