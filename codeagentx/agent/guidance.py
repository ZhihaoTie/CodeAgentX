"""Runtime tool-planning guidance derived from retry strategies."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from .state import AgentAction, utc_now_iso


WRITE_TOOLS = {"edit_file", "write_file"}


class ToolGuidanceStatus(Enum):
    ALIGNED = "aligned"
    WARNING = "warning"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ToolGuidanceCheck:
    status: ToolGuidanceStatus
    reason: str
    strategy: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        return self.status == ToolGuidanceStatus.BLOCKED

    @property
    def warning(self) -> bool:
        return self.status == ToolGuidanceStatus.WARNING

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "reason": self.reason,
            "strategy": self.strategy,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ToolPlanningGuidance:
    """Concrete runtime guardrails produced from a retry strategy."""

    strategy: str
    retry_index: int
    actions: list[str] = field(default_factory=list)
    preferred_tools: list[str] = field(default_factory=list)
    guarded_write_tools: list[str] = field(default_factory=lambda: sorted(WRITE_TOOLS))
    blocked_write_patterns: list[str] = field(default_factory=list)
    required_changed_patterns: list[str] = field(default_factory=list)
    blocked_repeated_actions: list[Mapping[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    workspace_root: str = "."
    created_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def from_retry_decision(
        cls,
        decision: Mapping[str, Any],
        reflection_report: Mapping[str, Any] | None,
        *,
        config: Any | None = None,
    ) -> "ToolPlanningGuidance | None":
        strategy = decision.get("strategy")
        if not isinstance(strategy, Mapping):
            return None

        strategy_name = str(strategy.get("strategy") or "")
        if not strategy_name:
            return None

        actions = _string_list(strategy.get("actions", []))
        categories = _string_list(strategy.get("categories", []))
        retry_index = int(decision.get("retry_index", 0) or 0)
        workspace_root = str(getattr(config, "workspace_root", ".") if config is not None else ".")
        config_forbidden = _string_list(getattr(config, "task_forbidden_changed_paths", []))
        config_required = _string_list(getattr(config, "task_required_changed_paths", []))
        patch_policy_forbidden = _string_list(getattr(config, "patch_policy_forbidden_paths", []))

        evidence = _reflection_evidence(reflection_report)
        blocked_patterns = _unique(
            _forbidden_patterns_from_evidence(evidence)
            + (config_forbidden if strategy_name == "task_constraint_repair" else [])
            + (patch_policy_forbidden if strategy_name == "patch_scope_reduction" else [])
        )
        required_patterns = _unique(
            _required_patterns_from_evidence(evidence)
            + (config_required if strategy_name == "task_constraint_repair" else [])
        )
        blocked_repeated = _blocked_repeated_actions(evidence)

        return cls(
            strategy=strategy_name,
            retry_index=retry_index,
            actions=actions,
            preferred_tools=_preferred_tools(strategy_name, categories),
            blocked_write_patterns=blocked_patterns,
            required_changed_patterns=required_patterns,
            blocked_repeated_actions=blocked_repeated,
            notes=_notes_for(strategy_name, blocked_patterns, required_patterns, blocked_repeated),
            workspace_root=workspace_root,
        )

    def evaluate(self, action: AgentAction) -> ToolGuidanceCheck:
        repeated = _matching_repeated_action(action, self.blocked_repeated_actions)
        if repeated is not None:
            return ToolGuidanceCheck(
                status=ToolGuidanceStatus.BLOCKED,
                reason="retry guidance blocked an exact repeat of a failed action",
                strategy=self.strategy,
                metadata={"blocked_action": repeated},
            )

        action_path = _action_path(action, self.workspace_root)
        if action.tool_name in WRITE_TOOLS and action_path:
            pattern = _matching_pattern(action_path, self.blocked_write_patterns)
            if pattern is not None:
                return ToolGuidanceCheck(
                    status=ToolGuidanceStatus.BLOCKED,
                    reason=f"retry guidance blocks writes matching forbidden pattern: {pattern}",
                    strategy=self.strategy,
                    metadata={
                        "path": action_path,
                        "pattern": pattern,
                        "guarded_tool": action.tool_name,
                    },
                )

        if self.preferred_tools and action.tool_name not in self.preferred_tools:
            return ToolGuidanceCheck(
                status=ToolGuidanceStatus.WARNING,
                reason="tool is outside the preferred set for the retry strategy",
                strategy=self.strategy,
                metadata={
                    "tool_name": action.tool_name,
                    "preferred_tools": list(self.preferred_tools),
                },
            )

        if (
            self.strategy == "patch_scope_reduction"
            and action.tool_name in WRITE_TOOLS
            and not self.blocked_write_patterns
        ):
            return ToolGuidanceCheck(
                status=ToolGuidanceStatus.WARNING,
                reason="retry strategy requires reduced patch scope before additional writes",
                strategy=self.strategy,
                metadata={"tool_name": action.tool_name, "path": action_path},
            )

        return ToolGuidanceCheck(
            status=ToolGuidanceStatus.ALIGNED,
            reason="tool call aligns with retry planning guidance",
            strategy=self.strategy,
            metadata={"tool_name": action.tool_name},
        )

    def prompt_fragment(self) -> str:
        lines = [
            f"- Runtime guidance strategy: {self.strategy}",
            "- Tool calls are checked against this guidance before execution.",
        ]
        if self.preferred_tools:
            lines.append("- Preferred tools: " + ", ".join(self.preferred_tools))
        if self.blocked_write_patterns:
            lines.append("- Blocked write path patterns: " + ", ".join(self.blocked_write_patterns))
        if self.required_changed_patterns:
            lines.append("- Required changed path patterns: " + ", ".join(self.required_changed_patterns))
        if self.blocked_repeated_actions:
            lines.append("- Exact repeats of the last failed action pattern may be blocked.")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "retry_index": self.retry_index,
            "actions": list(self.actions),
            "preferred_tools": list(self.preferred_tools),
            "guarded_write_tools": list(self.guarded_write_tools),
            "blocked_write_patterns": list(self.blocked_write_patterns),
            "required_changed_patterns": list(self.required_changed_patterns),
            "blocked_repeated_actions": [dict(item) for item in self.blocked_repeated_actions],
            "notes": list(self.notes),
            "created_at": self.created_at,
        }


def _reflection_evidence(reflection_report: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    if not isinstance(reflection_report, Mapping):
        return []
    signals = reflection_report.get("signals", [])
    if not isinstance(signals, list):
        return []
    evidence: list[Mapping[str, Any]] = []
    for signal in signals:
        if not isinstance(signal, Mapping):
            continue
        payload = signal.get("evidence", {})
        if isinstance(payload, Mapping):
            evidence.append(payload)
    return evidence


def _forbidden_patterns_from_evidence(evidence_items: list[Mapping[str, Any]]) -> list[str]:
    patterns: list[str] = []
    for evidence in evidence_items:
        for violation in _violation_items(evidence):
            if violation.get("type") == "forbidden_changed_path_modified":
                pattern = violation.get("pattern")
                if pattern is not None:
                    patterns.append(str(pattern))
        for violation in _violation_items(evidence):
            if violation.get("rule") == "forbidden_path":
                pattern = violation.get("pattern") or violation.get("path")
                if pattern is not None:
                    patterns.append(str(pattern))
    return patterns


def _required_patterns_from_evidence(evidence_items: list[Mapping[str, Any]]) -> list[str]:
    patterns: list[str] = []
    for evidence in evidence_items:
        for violation in _violation_items(evidence):
            if violation.get("type") == "required_changed_path_missing":
                pattern = violation.get("pattern")
                if pattern is not None:
                    patterns.append(str(pattern))
    return patterns


def _blocked_repeated_actions(evidence_items: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    blocked: list[Mapping[str, Any]] = []
    for evidence in evidence_items:
        tool_name = evidence.get("tool_name")
        tool_input = evidence.get("tool_input")
        if tool_name and isinstance(tool_input, Mapping):
            blocked.append({
                "tool_name": str(tool_name),
                "tool_input": dict(tool_input),
            })
    return blocked


def _violation_items(evidence: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    violations = evidence.get("violations", [])
    if not isinstance(violations, list):
        return []
    return [item for item in violations if isinstance(item, Mapping)]


def _preferred_tools(strategy_name: str, categories: list[str]) -> list[str]:
    base = ["read_file", "grep", "glob", "ast_context"]
    if strategy_name in {
        "focused_test_fix",
        "verification_reproduction",
        "sandbox_adjustment",
    } or "test_failure" in categories:
        base.append("bash")
    if strategy_name in {
        "task_constraint_repair",
        "patch_scope_reduction",
        "focused_test_fix",
        "verification_reproduction",
    }:
        base.extend(sorted(WRITE_TOOLS))
    if strategy_name == "final_response_recovery":
        return []
    return _unique(base)


def _notes_for(
    strategy_name: str,
    blocked_patterns: list[str],
    required_patterns: list[str],
    blocked_repeated: list[Mapping[str, Any]],
) -> list[str]:
    notes: list[str] = []
    if blocked_patterns:
        notes.append("write tools are blocked for forbidden retry path patterns")
    if required_patterns:
        notes.append("retry should satisfy required changed path patterns")
    if blocked_repeated:
        notes.append("exact repeated failed actions are blocked")
    if strategy_name == "patch_scope_reduction":
        notes.append("additional writes should be justified by reduced patch scope")
    return notes


def _action_path(action: AgentAction, workspace_root: str) -> str | None:
    raw_path = action.tool_input.get("path")
    if raw_path in (None, ""):
        return None
    return _normalize_path(str(raw_path), Path(workspace_root).expanduser().resolve())


def _normalize_path(raw_path: str, workspace_root: Path) -> str:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        return _posix(path)
    try:
        return _posix(path.resolve(strict=False).relative_to(workspace_root))
    except ValueError:
        return _posix(path)


def _matching_pattern(path: str, patterns: list[str]) -> str | None:
    normalized_path = path.replace("\\", "/")
    basename = Path(normalized_path).name
    for pattern in patterns:
        normalized_pattern = str(pattern).replace("\\", "/")
        if (
            fnmatch.fnmatch(normalized_path, normalized_pattern)
            or fnmatch.fnmatch(basename, normalized_pattern)
        ):
            return pattern
    return None


def _matching_repeated_action(
    action: AgentAction,
    blocked_actions: list[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    for blocked in blocked_actions:
        if str(blocked.get("tool_name", "")) != action.tool_name:
            continue
        tool_input = blocked.get("tool_input")
        if isinstance(tool_input, Mapping) and dict(tool_input) == dict(action.tool_input):
            return blocked
    return None


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _posix(path: Path) -> str:
    return "/".join(path.parts)
