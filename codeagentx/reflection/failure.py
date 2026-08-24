"""Deterministic failure reflection for agent trajectories."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from codeagentx.agent.state import AgentState, utc_now_iso


class FailureCategory(Enum):
    """High-level causes extracted from runtime evidence."""

    VERIFICATION_FAILED = "verification_failed"
    TEST_FAILURE = "test_failure"
    SANDBOX_TIMEOUT = "sandbox_timeout"
    SANDBOX_VIOLATION = "sandbox_violation"
    SANDBOX_ERROR = "sandbox_error"
    TASK_CONSTRAINT_VIOLATION = "task_constraint_violation"
    PATCH_POLICY_VIOLATION = "patch_policy_violation"
    TOOL_ERRORS = "tool_errors"
    NO_FINAL_RESPONSE = "no_final_response"
    NO_PROGRESS = "no_progress"
    ROLLBACK_FAILED = "rollback_failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class FailureSignal:
    category: FailureCategory
    severity: str
    message: str
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "severity": self.severity,
            "message": self.message,
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True)
class FailureReflectionReport:
    status: str
    summary: str
    retryable: bool
    signals: list[FailureSignal] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "retryable": self.retryable,
            "signals": [signal.to_dict() for signal in self.signals],
            "recommendations": list(self.recommendations),
            "created_at": self.created_at,
        }


class FailureReflector:
    """Summarize failed runs into auditable retry signals.

    The reflector deliberately does not call a model or execute tools. It only
    reads AgentState evidence so retry/replan policies can be evaluated
    independently later.
    """

    def reflect(self, state: AgentState, final_text: str = "") -> FailureReflectionReport:
        signals: list[FailureSignal] = []

        verification_report = _mapping(getattr(state, "verification_report", None))
        if verification_report:
            signals.extend(_verification_signals(verification_report, final_text))

        signals.extend(_patch_policy_signals(_mapping(getattr(state, "patch_policy_report", None))))
        signals.extend(_tool_error_signals(state))
        signals.extend(_no_progress_signals(state))
        signals.extend(_rollback_signals(_mapping(getattr(state, "rollback_report", None))))

        if not signals:
            signals.append(FailureSignal(
                category=FailureCategory.UNKNOWN,
                severity="warning",
                message="Task failed without a recognized failure signal.",
                evidence={"failure_reason": getattr(state, "failure_reason", "")},
            ))

        categories = [signal.category.value for signal in signals]
        retryable = _is_retryable(signals)
        recommendations = _recommendations_for(signals)
        summary = _summary_for(categories, retryable)

        return FailureReflectionReport(
            status="generated",
            summary=summary,
            retryable=retryable,
            signals=signals,
            recommendations=recommendations,
        )


def _verification_signals(
    report: Mapping[str, Any],
    final_text: str,
) -> list[FailureSignal]:
    signals: list[FailureSignal] = []
    checks = report.get("checks", [])
    if not isinstance(checks, list):
        checks = []

    for check in checks:
        check_map = _mapping(check)
        name = str(check_map.get("name", ""))
        status = str(check_map.get("status", ""))
        message = str(check_map.get("message", ""))
        metadata = _mapping(check_map.get("metadata"))

        if name == "final_response" and status == "failed":
            signals.append(FailureSignal(
                category=FailureCategory.NO_FINAL_RESPONSE,
                severity="error",
                message=message or "Model stopped without a final response.",
                evidence={"final_text_chars": len(final_text or "")},
            ))

        if name == "task_constraints" and status == "failed":
            signals.append(FailureSignal(
                category=FailureCategory.TASK_CONSTRAINT_VIOLATION,
                severity="error",
                message=message or "Task constraints failed.",
                evidence=_constraint_evidence(metadata),
            ))

        if name != "verification_command":
            continue

        sandbox = _mapping(metadata.get("sandbox"))
        sandbox_status = str(sandbox.get("status", ""))
        if sandbox_status == "timed_out" or metadata.get("timed_out") is True:
            signals.append(FailureSignal(
                category=FailureCategory.SANDBOX_TIMEOUT,
                severity="error",
                message=message or "Verification command timed out.",
                evidence=_command_evidence(metadata, sandbox),
            ))
        elif sandbox_status == "violation":
            signals.append(FailureSignal(
                category=FailureCategory.SANDBOX_VIOLATION,
                severity="critical",
                message=str(sandbox.get("violation") or message or "Sandbox policy violation."),
                evidence=_command_evidence(metadata, sandbox),
            ))
        elif sandbox_status == "error":
            signals.append(FailureSignal(
                category=FailureCategory.SANDBOX_ERROR,
                severity="error",
                message=str(sandbox.get("error_type") or message or "Sandbox execution error."),
                evidence=_command_evidence(metadata, sandbox),
            ))

        test_result = _mapping(metadata.get("test_result"))
        if _has_test_failures(test_result):
            signals.append(FailureSignal(
                category=FailureCategory.TEST_FAILURE,
                severity="error",
                message=_test_failure_message(test_result),
                evidence={
                    "framework": test_result.get("framework"),
                    "status": test_result.get("status"),
                    "total": test_result.get("total"),
                    "passed": test_result.get("passed"),
                    "failed": int(test_result.get("failed", 0) or 0),
                    "errors": int(test_result.get("errors", 0) or 0),
                    "skipped": int(test_result.get("skipped", 0) or 0),
                    "failure_names": list(test_result.get("failure_names") or [])[:10],
                },
            ))

        if status == "failed":
            signals.append(FailureSignal(
                category=FailureCategory.VERIFICATION_FAILED,
                severity="error",
                message=message or "Verification command failed.",
                evidence=_command_evidence(metadata, sandbox),
            ))

    if not signals and str(report.get("status", "")) == "failed":
        signals.append(FailureSignal(
            category=FailureCategory.VERIFICATION_FAILED,
            severity="error",
            message=str(report.get("summary") or "Verification failed."),
            evidence={"report_status": report.get("status")},
        ))

    return signals


def _tool_error_signals(state: AgentState) -> list[FailureSignal]:
    error_steps = [
        step for step in state.trajectory
        if step.observation.is_error
    ]
    if not error_steps:
        return []

    by_tool = Counter(step.action.tool_name for step in error_steps)
    samples = [
        {
            "turn": step.turn,
            "tool_name": step.action.tool_name,
            "output": _truncate(step.observation.output),
        }
        for step in error_steps[-3:]
    ]
    return [FailureSignal(
        category=FailureCategory.TOOL_ERRORS,
        severity="warning",
        message=f"{len(error_steps)} tool call(s) returned errors.",
        evidence={
            "count": len(error_steps),
            "by_tool": dict(sorted(by_tool.items())),
            "samples": samples,
        },
    )]


def _patch_policy_signals(report: Mapping[str, Any]) -> list[FailureSignal]:
    if not report or str(report.get("status", "")) != "failed":
        return []

    violations = report.get("violations", [])
    violation_payloads = [
        dict(violation) for violation in violations
        if isinstance(violation, Mapping)
    ]
    critical = any(
        str(violation.get("severity", "")) == "critical"
        for violation in violation_payloads
    )
    return [FailureSignal(
        category=FailureCategory.PATCH_POLICY_VIOLATION,
        severity="critical" if critical else "error",
        message=str(report.get("summary") or "Patch policy failed."),
        evidence={
            "status": report.get("status"),
            "changed_files": report.get("changed_files"),
            "patch_count": report.get("patch_count"),
            "total_changed_lines": report.get("total_changed_lines"),
            "critical": critical,
            "violations": violation_payloads[:10],
        },
    )]


def _no_progress_signals(state: AgentState) -> list[FailureSignal]:
    if not state.trajectory:
        return [FailureSignal(
            category=FailureCategory.NO_PROGRESS,
            severity="warning",
            message="Task failed before recording any tool trajectory.",
            evidence={"turns": 0},
        )]

    if len(state.trajectory) < 3:
        return []

    recent = state.trajectory[-3:]
    signatures = {
        (
            step.action.tool_name,
            tuple(sorted((str(key), repr(value)) for key, value in step.action.tool_input.items())),
        )
        for step in recent
    }
    if len(signatures) == 1 and all(step.observation.is_error for step in recent):
        step = recent[-1]
        return [FailureSignal(
            category=FailureCategory.NO_PROGRESS,
            severity="warning",
            message="The last three actions repeated the same failed tool call.",
            evidence={
                "tool_name": step.action.tool_name,
                "tool_input": dict(step.action.tool_input),
                "turns": [item.turn for item in recent],
            },
        )]
    return []


def _rollback_signals(report: Mapping[str, Any]) -> list[FailureSignal]:
    if not report:
        return []
    failed = int(report.get("failed", 0) or 0)
    if failed <= 0:
        return []
    return [FailureSignal(
        category=FailureCategory.ROLLBACK_FAILED,
        severity="critical",
        message=f"Rollback failed for {failed} patch transaction(s).",
        evidence={
            "status": report.get("status"),
            "attempted": int(report.get("attempted", 0) or 0),
            "restored": int(report.get("restored", 0) or 0),
            "failed": failed,
        },
    )]


def _command_evidence(
    metadata: Mapping[str, Any],
    sandbox: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "command": metadata.get("command"),
        "cwd": metadata.get("cwd"),
        "exit_code": metadata.get("exit_code"),
        "timeout_seconds": metadata.get("timeout_seconds"),
        "sandbox_type": sandbox.get("sandbox_type"),
        "sandbox_status": sandbox.get("status"),
        "timed_out": bool(sandbox.get("timed_out", metadata.get("timed_out", False))),
        "violation": sandbox.get("violation"),
        "error_type": sandbox.get("error_type"),
    }


def _constraint_evidence(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "deterministic": metadata.get("deterministic"),
        "violation_count": metadata.get("violation_count"),
        "success_criteria": list(metadata.get("success_criteria") or [])[:10],
        "changed_paths": list(metadata.get("changed_paths") or [])[:20],
        "violations": list(metadata.get("violations") or [])[:10],
    }


def _has_test_failures(test_result: Mapping[str, Any]) -> bool:
    if not test_result or not test_result.get("recognized"):
        return False
    return (
        int(test_result.get("failed", 0) or 0) > 0
        or int(test_result.get("errors", 0) or 0) > 0
        or str(test_result.get("status", "")) == "failed"
    )


def _test_failure_message(test_result: Mapping[str, Any]) -> str:
    failed = int(test_result.get("failed", 0) or 0)
    errors = int(test_result.get("errors", 0) or 0)
    total = test_result.get("total")
    framework = test_result.get("framework", "tests")
    return f"{framework} reported {failed} failed and {errors} errored tests out of {total}."


def _recommendations_for(signals: list[FailureSignal]) -> list[str]:
    recommendations: list[str] = []
    categories = {signal.category for signal in signals}

    if FailureCategory.TEST_FAILURE in categories:
        recommendations.append("Inspect failing test names and rerun a focused verification command.")
        recommendations.append("Read the code paths touched by the failing tests before editing again.")
    if FailureCategory.VERIFICATION_FAILED in categories and FailureCategory.TEST_FAILURE not in categories:
        recommendations.append("Check verification stdout/stderr and reproduce the command locally.")
    if FailureCategory.SANDBOX_TIMEOUT in categories:
        recommendations.append("Use a narrower verification command or increase the timeout budget.")
    if FailureCategory.SANDBOX_VIOLATION in categories:
        recommendations.append("Fix the workspace root/cwd or remove out-of-workspace execution.")
    if FailureCategory.SANDBOX_ERROR in categories:
        recommendations.append("Inspect sandbox error metadata before retrying the task.")
    if FailureCategory.PATCH_POLICY_VIOLATION in categories:
        recommendations.append("Inspect patch policy violations before applying more edits.")
        recommendations.append("Reduce patch scope or avoid forbidden files before retrying.")
    if FailureCategory.TASK_CONSTRAINT_VIOLATION in categories:
        recommendations.append("Inspect task constraint violations before applying more edits.")
        recommendations.append("Satisfy required changed paths and avoid forbidden task paths before retrying.")
    if FailureCategory.TOOL_ERRORS in categories:
        recommendations.append("Review failed tool observations and correct the next tool inputs.")
    if FailureCategory.NO_PROGRESS in categories:
        recommendations.append("Change strategy before retrying; repeating the same action is unlikely to help.")
    if FailureCategory.ROLLBACK_FAILED in categories:
        recommendations.append("Manually inspect rollback results before applying more edits.")
    if FailureCategory.NO_FINAL_RESPONSE in categories:
        recommendations.append("Ask for a concise final answer after collecting enough evidence.")
    if not recommendations:
        recommendations.append("Collect more context and rerun explicit verification.")

    return _unique(recommendations)


def _is_retryable(signals: list[FailureSignal]) -> bool:
    non_retryable = {
        FailureCategory.SANDBOX_VIOLATION,
        FailureCategory.ROLLBACK_FAILED,
    }
    if any(signal.category in non_retryable for signal in signals):
        return False
    return not any(
        signal.category == FailureCategory.PATCH_POLICY_VIOLATION
        and bool(signal.evidence.get("critical", False))
        for signal in signals
    )


def _summary_for(categories: list[str], retryable: bool) -> str:
    counts = Counter(categories)
    ordered = ", ".join(f"{category}:{count}" for category, count in sorted(counts.items()))
    retry_text = "retryable" if retryable else "requires intervention"
    return f"Failure reflection generated ({retry_text}); signals={ordered}."


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def _truncate(value: Any, max_chars: int = 500) -> str:
    text = "" if value is None else str(value)
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return text[:max_chars] + f"\n... output truncated {omitted} chars"


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
