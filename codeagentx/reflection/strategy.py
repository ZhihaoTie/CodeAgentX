"""Retry strategy selection from failure reflection evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from codeagentx.agent.state import utc_now_iso


class RetryStrategyName(Enum):
    FOCUSED_TEST_FIX = "focused_test_fix"
    TASK_CONSTRAINT_REPAIR = "task_constraint_repair"
    PATCH_SCOPE_REDUCTION = "patch_scope_reduction"
    SANDBOX_ADJUSTMENT = "sandbox_adjustment"
    TOOL_INPUT_CORRECTION = "tool_input_correction"
    CHANGE_APPROACH = "change_approach"
    FINAL_RESPONSE_RECOVERY = "final_response_recovery"
    VERIFICATION_REPRODUCTION = "verification_reproduction"
    COLLECT_MORE_CONTEXT = "collect_more_context"
    STOP_FOR_INTERVENTION = "stop_for_intervention"


@dataclass(frozen=True)
class RetryStrategyPlan:
    strategy: RetryStrategyName
    should_retry: bool
    actions: list[str] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    prompt_instructions: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy.value,
            "should_retry": self.should_retry,
            "actions": list(self.actions),
            "rationale": list(self.rationale),
            "categories": list(self.categories),
            "prompt_instructions": list(self.prompt_instructions),
            "created_at": self.created_at,
        }


class RetryStrategyMatrix:
    """Map reflection categories to a concrete retry strategy."""

    def decide(
        self,
        reflection_report: Mapping[str, Any] | None,
        *,
        ranked_context_report: Mapping[str, Any] | None = None,
    ) -> RetryStrategyPlan:
        if not isinstance(reflection_report, Mapping):
            return RetryStrategyPlan(
                strategy=RetryStrategyName.STOP_FOR_INTERVENTION,
                should_retry=False,
                actions=["request_intervention"],
                rationale=["no reflection report is available"],
                categories=[],
                prompt_instructions=["Stop and ask for human inspection before retrying."],
            )

        categories = _categories(reflection_report)
        retryable = bool(reflection_report.get("retryable", False))
        actions: list[str] = []
        rationale: list[str] = []
        instructions: list[str] = []

        if _has_ranked_context(ranked_context_report):
            actions.append("inspect_ranked_context")
            instructions.append("Start from the ranked context candidates before reading unrelated files.")
        else:
            actions.append("collect_targeted_context")
            instructions.append("Collect targeted context before editing again.")

        if not retryable:
            actions.append("request_intervention")
            rationale.append("reflection report marked the failure as non-retryable")
            instructions.append("Do not apply more edits until the blocking failure is resolved.")
            return RetryStrategyPlan(
                strategy=RetryStrategyName.STOP_FOR_INTERVENTION,
                should_retry=False,
                actions=_unique(actions),
                rationale=_unique(rationale),
                categories=categories,
                prompt_instructions=_unique(instructions),
            )

        if _contains(categories, "rollback_failed", "sandbox_violation"):
            actions.append("request_intervention")
            rationale.append("failure requires external or workspace-level intervention")
            instructions.append("Stop instead of retrying automatically; inspect sandbox or rollback evidence.")
            return RetryStrategyPlan(
                strategy=RetryStrategyName.STOP_FOR_INTERVENTION,
                should_retry=False,
                actions=_unique(actions),
                rationale=_unique(rationale),
                categories=categories,
                prompt_instructions=_unique(instructions),
            )

        strategy = RetryStrategyName.COLLECT_MORE_CONTEXT
        if "task_constraint_violation" in categories:
            strategy = RetryStrategyName.TASK_CONSTRAINT_REPAIR
            actions.extend(["inspect_task_constraints", "satisfy_required_constraints", "avoid_forbidden_changes"])
            rationale.append("task constraint violations directly block final acceptance")
            instructions.extend([
                "Inspect task constraint violations before applying more edits.",
                "Satisfy required changed paths or final response requirements, and avoid forbidden task paths.",
            ])
        elif "patch_policy_violation" in categories:
            strategy = RetryStrategyName.PATCH_SCOPE_REDUCTION
            actions.extend(["inspect_patch_policy", "reduce_patch_scope"])
            rationale.append("patch policy violations should be addressed before broader edits")
            instructions.extend([
                "Inspect patch policy violations before applying more edits.",
                "Reduce patch size, avoid forbidden paths, and keep the fix scoped to the task.",
            ])
        elif "test_failure" in categories:
            strategy = RetryStrategyName.FOCUSED_TEST_FIX
            actions.extend(["inspect_failing_tests", "rerun_focused_tests", "apply_minimal_fix"])
            rationale.append("failing tests provide the strongest repair signal")
            instructions.extend([
                "Use failing test names and ranked context to identify the smallest plausible fix.",
                "Rerun the narrowest verification command that reproduces the failing tests before broad checks.",
            ])
        elif _contains(categories, "sandbox_timeout", "sandbox_error"):
            strategy = RetryStrategyName.SANDBOX_ADJUSTMENT
            actions.extend(["inspect_sandbox_metadata", "narrow_verification_command"])
            rationale.append("sandbox failures should be resolved before changing unrelated source code")
            instructions.extend([
                "Inspect sandbox metadata before changing source code.",
                "Use a narrower command or adjust sandbox settings only when the task requires it.",
            ])
        elif "tool_errors" in categories:
            strategy = RetryStrategyName.TOOL_INPUT_CORRECTION
            actions.extend(["inspect_tool_errors", "correct_tool_inputs"])
            rationale.append("failed tool observations indicate bad parameters or missing context")
            instructions.append("Correct the failed tool input before repeating a similar tool call.")
        elif "verification_failed" in categories:
            strategy = RetryStrategyName.VERIFICATION_REPRODUCTION
            actions.extend(["inspect_verification_output", "rerun_verification", "apply_minimal_fix"])
            rationale.append("verification output must be reproduced before further edits")
            instructions.append("Inspect stdout/stderr and reproduce the verification failure before editing.")
        elif "no_progress" in categories:
            strategy = RetryStrategyName.CHANGE_APPROACH
            actions.extend(["change_approach", "avoid_repeated_actions"])
            rationale.append("recent actions repeated the same failure pattern")
            instructions.append("Change approach; do not repeat the same failed action.")
        elif "no_final_response" in categories:
            strategy = RetryStrategyName.FINAL_RESPONSE_RECOVERY
            actions.extend(["verify_current_state", "produce_final_response"])
            rationale.append("the run failed because the model stopped without a final response")
            instructions.append("If the code is already fixed, verify and provide a concise final response.")
        else:
            actions.extend(["collect_more_context", "rerun_explicit_verification"])
            rationale.append("no specialized strategy matched the available failure categories")
            instructions.append("Collect more context and rerun explicit verification.")

        return RetryStrategyPlan(
            strategy=strategy,
            should_retry=True,
            actions=_unique(actions),
            rationale=_unique(rationale),
            categories=categories,
            prompt_instructions=_unique(instructions),
        )


def _categories(report: Mapping[str, Any]) -> list[str]:
    signals = report.get("signals", [])
    categories: list[str] = []
    if not isinstance(signals, list):
        return categories
    for signal in signals:
        if not isinstance(signal, Mapping):
            continue
        category = signal.get("category")
        if category is not None:
            categories.append(str(category))
    return _unique(categories)


def _has_ranked_context(report: Mapping[str, Any] | None) -> bool:
    if not isinstance(report, Mapping):
        return False
    candidates = report.get("candidates", [])
    return isinstance(candidates, list) and len(candidates) > 0


def _contains(values: list[str], *needles: str) -> bool:
    return any(needle in values for needle in needles)


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
