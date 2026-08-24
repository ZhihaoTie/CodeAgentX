"""Planning data structures for software engineering tasks.

The first version deliberately keeps planning model-agnostic: an LLM planner can
produce this schema later, while tests and deterministic components can create
plans directly today.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping


class PlanStepStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    BLOCKED = "blocked"


class PlanStepKind(Enum):
    UNDERSTAND_TASK = "understand_task"
    INSPECT_CONTEXT = "inspect_context"
    MODIFY_WORKSPACE = "modify_workspace"
    SATISFY_CONSTRAINTS = "satisfy_constraints"
    VERIFY_OUTCOME = "verify_outcome"
    RECOVER_FAILURE = "recover_failure"
    FINAL_RESPONSE = "final_response"


@dataclass
class PlanStep:
    index: int
    description: str
    kind: str = ""
    status: PlanStepStatus = PlanStepStatus.PENDING
    evidence: str = ""

    def mark_started(self) -> None:
        self.status = PlanStepStatus.IN_PROGRESS

    def mark_done(self, evidence: str = "") -> None:
        self.status = PlanStepStatus.DONE
        self.evidence = evidence

    def mark_blocked(self, evidence: str) -> None:
        self.status = PlanStepStatus.BLOCKED
        self.evidence = evidence

    def to_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "kind": self.kind,
            "description": self.description,
            "status": self.status.value,
            "evidence": self.evidence,
        }


@dataclass
class TaskPlan:
    goal: str
    steps: list[PlanStep] = field(default_factory=list)

    @classmethod
    def from_steps(cls, goal: str, steps: list[str]) -> "TaskPlan":
        return cls(
            goal=goal,
            steps=[
                PlanStep(index=i + 1, kind=f"step_{i + 1}", description=step)
                for i, step in enumerate(steps)
            ],
        )

    @classmethod
    def from_items(cls, goal: str, items: list[tuple[str, str]]) -> "TaskPlan":
        return cls(
            goal=goal,
            steps=[
                PlanStep(index=i + 1, kind=kind, description=description)
                for i, (kind, description) in enumerate(items)
            ],
        )

    def next_pending(self) -> PlanStep | None:
        for step in self.steps:
            if step.status == PlanStepStatus.PENDING:
                return step
        return None

    def step_by_kind(self, kind: str | PlanStepKind) -> PlanStep | None:
        value = kind.value if isinstance(kind, PlanStepKind) else str(kind)
        for step in self.steps:
            if step.kind == value:
                return step
        return None

    def add_steps(self, items: list[tuple[str, str]]) -> list[PlanStep]:
        added: list[PlanStep] = []
        for kind, description in items:
            step = PlanStep(
                index=len(self.steps) + 1,
                kind=kind,
                description=description,
            )
            self.steps.append(step)
            added.append(step)
        return added

    def is_complete(self) -> bool:
        return bool(self.steps) and all(step.status == PlanStepStatus.DONE for step in self.steps)

    def progress(self) -> float:
        if not self.steps:
            return 0.0
        done = sum(1 for step in self.steps if step.status == PlanStepStatus.DONE)
        return done / len(self.steps)

    def completed_count(self) -> int:
        return sum(1 for step in self.steps if step.status == PlanStepStatus.DONE)

    def blocked_count(self) -> int:
        return sum(1 for step in self.steps if step.status == PlanStepStatus.BLOCKED)

    def to_dict(self) -> dict[str, object]:
        return {
            "goal": self.goal,
            "steps": [step.to_dict() for step in self.steps],
            "progress": self.progress(),
            "completed_steps": self.completed_count(),
            "blocked_steps": self.blocked_count(),
        }


@dataclass(frozen=True)
class PlanRepair:
    retry_index: int
    strategy: str
    target_step_kind: str
    reason: str
    actions: list[str] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)
    focused_test_targets: list[str] = field(default_factory=list)
    focused_test_command: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_plan_items(self) -> list[tuple[str, str]]:
        items: list[tuple[str, str]] = []
        for action in self.actions[:6]:
            description = _repair_action_description(action, self)
            items.append((f"repair_{self.retry_index}_{action}", description))
        if not items:
            items.append((
                f"repair_{self.retry_index}_recover",
                "Use failure evidence to choose a focused recovery action before broad verification.",
            ))
        return items

    def prompt_fragment(self) -> str:
        lines = [
            f"- Repair strategy: {self.strategy}",
            f"- Target plan step: {self.target_step_kind}",
        ]
        if self.actions:
            lines.append("- Planner repair actions:")
            lines.extend(f"  - {item}" for item in self.actions[:8])
        if self.instructions:
            lines.append("- Planner repair instructions:")
            lines.extend(f"  - {item}" for item in self.instructions[:8])
        if self.focused_test_targets:
            lines.append("- Focused test targets: " + ", ".join(self.focused_test_targets[:6]))
        if self.focused_test_command:
            lines.append("- Suggested focused test command: " + self.focused_test_command)
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "retry_index": self.retry_index,
            "strategy": self.strategy,
            "target_step_kind": self.target_step_kind,
            "reason": self.reason,
            "actions": list(self.actions),
            "instructions": list(self.instructions),
            "focused_test_targets": list(self.focused_test_targets),
            "focused_test_command": self.focused_test_command,
            "created_at": self.created_at,
        }


def build_runtime_plan(goal: str, config: Any) -> TaskPlan:
    """Create a conservative controller plan for a software-engineering run."""

    items: list[tuple[str, str]] = [
        (
            PlanStepKind.UNDERSTAND_TASK.value,
            "Clarify the objective, constraints, permission mode, and workspace boundary.",
        ),
        (
            PlanStepKind.INSPECT_CONTEXT.value,
            "Inspect relevant files, symbols, searches, or tool feedback before editing.",
        ),
    ]

    permission_mode = getattr(getattr(config, "permission_mode", None), "value", "")
    if permission_mode == "plan":
        items.append((
            PlanStepKind.MODIFY_WORKSPACE.value,
            "Keep the run read-only and identify the minimal changes that would be needed.",
        ))
    else:
        items.append((
            PlanStepKind.MODIFY_WORKSPACE.value,
            "Apply scoped changes through patch-aware tools when the evidence supports editing.",
        ))

    if _has_task_constraints(config):
        items.append((
            PlanStepKind.SATISFY_CONSTRAINTS.value,
            "Satisfy required task constraints and avoid forbidden paths or final-response text.",
        ))

    if getattr(config, "verification_command", None):
        items.append((
            PlanStepKind.VERIFY_OUTCOME.value,
            "Run the configured verification command and inspect the structured result.",
        ))
    else:
        items.append((
            PlanStepKind.VERIFY_OUTCOME.value,
            "Evaluate the final response and deterministic task constraints.",
        ))

    if int(getattr(config, "max_reflection_retries", 0) or 0) > 0:
        items.append((
            PlanStepKind.RECOVER_FAILURE.value,
            "If verification fails, use reflection evidence and retry budget for a focused repair.",
        ))

    items.append((
        PlanStepKind.FINAL_RESPONSE.value,
        "Return a concise final response with verification status and important evidence.",
    ))

    return TaskPlan.from_items(goal, items)


def build_plan_repair(
    decision: Mapping[str, Any],
    reflection_report: Mapping[str, Any] | None,
    *,
    ranked_context_report: Mapping[str, Any] | None = None,
    config: Any | None = None,
) -> PlanRepair | None:
    """Create planner-level repair guidance from a retry decision."""

    if str(decision.get("status", "")) != "retry":
        return None

    strategy = decision.get("strategy")
    strategy_map = strategy if isinstance(strategy, Mapping) else {}
    strategy_name = str(strategy_map.get("strategy") or "generic_retry")
    categories = _string_list(strategy_map.get("categories", decision.get("categories", [])))
    actions = _string_list(strategy_map.get("actions", []))
    instructions = _string_list(strategy_map.get("prompt_instructions", []))
    if not actions:
        actions = _default_repair_actions(strategy_name, categories)
    targets = _focused_test_targets(reflection_report)

    return PlanRepair(
        retry_index=int(decision.get("retry_index", 0) or 0),
        strategy=strategy_name,
        target_step_kind=_repair_target_step(strategy_name, categories),
        reason=str(decision.get("reason", "") or ""),
        actions=_unique(actions),
        instructions=_unique(instructions),
        focused_test_targets=targets,
        focused_test_command=_focused_test_command(
            targets,
            getattr(config, "verification_command", "") if config is not None else "",
        ),
    )


def _has_task_constraints(config: Any) -> bool:
    if not getattr(config, "enable_task_constraints", True):
        return False
    return any((
        getattr(config, "task_success_criteria", []),
        getattr(config, "task_required_changed_paths", []),
        getattr(config, "task_forbidden_changed_paths", []),
        getattr(config, "task_required_final_response_substrings", []),
        getattr(config, "task_forbidden_final_response_substrings", []),
    ))


def _repair_target_step(strategy_name: str, categories: list[str]) -> str:
    if strategy_name == "task_constraint_repair" or "task_constraint_violation" in categories:
        return PlanStepKind.SATISFY_CONSTRAINTS.value
    if strategy_name in {"focused_test_fix", "verification_reproduction", "sandbox_adjustment"}:
        return PlanStepKind.VERIFY_OUTCOME.value
    if strategy_name in {"patch_scope_reduction", "tool_input_correction"}:
        return PlanStepKind.MODIFY_WORKSPACE.value
    if strategy_name == "final_response_recovery":
        return PlanStepKind.FINAL_RESPONSE.value
    if strategy_name in {"collect_more_context", "change_approach"}:
        return PlanStepKind.INSPECT_CONTEXT.value
    return PlanStepKind.RECOVER_FAILURE.value


def _default_repair_actions(strategy_name: str, categories: list[str]) -> list[str]:
    if strategy_name == "focused_test_fix" or "test_failure" in categories:
        return ["inspect_failing_tests", "rerun_focused_tests", "apply_minimal_fix"]
    if strategy_name == "task_constraint_repair":
        return ["inspect_task_constraints", "satisfy_required_constraints", "avoid_forbidden_changes"]
    if strategy_name == "patch_scope_reduction":
        return ["inspect_patch_policy", "reduce_patch_scope"]
    if strategy_name == "tool_input_correction":
        return ["inspect_tool_errors", "correct_tool_inputs"]
    if strategy_name == "verification_reproduction":
        return ["inspect_verification_output", "rerun_verification", "apply_minimal_fix"]
    return ["collect_targeted_context", "retry_with_evidence"]


def _repair_action_description(action: str, repair: PlanRepair) -> str:
    descriptions = {
        "inspect_ranked_context": "Inspect ranked context candidates before reading unrelated files.",
        "collect_targeted_context": "Collect targeted context needed for the retry before editing again.",
        "inspect_failing_tests": "Inspect failing test names and related code paths.",
        "rerun_focused_tests": "Rerun the narrowest focused test command before broad verification.",
        "apply_minimal_fix": "Apply the smallest patch that addresses the repair evidence.",
        "inspect_task_constraints": "Inspect task constraint violations and required or forbidden paths.",
        "satisfy_required_constraints": "Satisfy required changed paths or final response constraints.",
        "avoid_forbidden_changes": "Avoid forbidden paths and reverse any off-scope changes.",
        "inspect_patch_policy": "Inspect patch policy violations before additional edits.",
        "reduce_patch_scope": "Reduce patch size and keep changes scoped to the task.",
        "inspect_sandbox_metadata": "Inspect sandbox metadata before changing source code.",
        "narrow_verification_command": "Use a narrower verification command when the failure supports it.",
        "inspect_tool_errors": "Review failed tool observations before repeating tool calls.",
        "correct_tool_inputs": "Correct bad tool inputs using the latest failure evidence.",
        "change_approach": "Change approach and avoid repeated failed actions.",
        "avoid_repeated_actions": "Avoid exact repeats of failed tool calls.",
        "verify_current_state": "Verify the current state before producing a final response.",
        "produce_final_response": "Produce a concise final response after evidence is sufficient.",
        "rerun_verification": "Reproduce the verification failure before broader checks.",
    }
    description = descriptions.get(action, f"Run repair action: {action}.")
    if action == "rerun_focused_tests" and repair.focused_test_command:
        return description + f" Suggested command: {repair.focused_test_command}"
    return description


def _focused_test_targets(reflection_report: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(reflection_report, Mapping):
        return []
    signals = reflection_report.get("signals", [])
    if not isinstance(signals, list):
        return []
    targets: list[str] = []
    for signal in signals:
        if not isinstance(signal, Mapping):
            continue
        evidence = signal.get("evidence", {})
        if not isinstance(evidence, Mapping):
            continue
        targets.extend(_string_list(evidence.get("failure_names", [])))
    return _unique(targets)[:6]


def _focused_test_command(targets: list[str], verification_command: Any) -> str:
    command = str(verification_command or "").strip()
    if not command or not targets:
        return ""
    lower = command.lower()
    selected = targets[:3]
    if "pytest" in lower:
        pytest_targets = [_normalize_pytest_target(target) for target in selected]
        path_targets = [
            target
            for target in pytest_targets
            if "::" in target or "/" in target or "\\" in target
        ]
        if path_targets:
            return command + " " + " ".join(path_targets)
        expression = " or ".join(pytest_targets)
        return command + f' -k "{expression}"'
    if "unittest" in lower:
        unittest_targets = [_normalize_unittest_target(target) for target in selected]
        if not all("." in target for target in unittest_targets):
            return ""
        if " discover" in lower:
            return "python -m unittest " + " ".join(unittest_targets)
        return command + " " + " ".join(unittest_targets)
    return ""


def _normalize_pytest_target(target: str) -> str:
    target = str(target).strip()
    if " - " in target:
        target = target.split(" - ", 1)[0].strip()
    return target


def _normalize_unittest_target(target: str) -> str:
    target = str(target).strip()
    if "(" in target and target.endswith(")"):
        candidate = target[target.rfind("(") + 1:-1].strip()
        if "." in candidate:
            return candidate
    return target


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
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
