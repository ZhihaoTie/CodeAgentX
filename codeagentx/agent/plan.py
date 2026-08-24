"""Runtime plan lifecycle control for CodeAgent-X."""

from __future__ import annotations

from typing import Any, Callable

from codeagentx.config import Config
from codeagentx.context import ConversationContext

from .planner import PlanStepKind, PlanStepStatus, build_runtime_plan
from .state import AgentAction, AgentObservation, AgentState


RecordEvent = Callable[[AgentState, str, dict[str, Any]], None]


class PlanController:
    """Owns runtime plan creation and progress updates."""

    def __init__(
        self,
        *,
        config: Config,
        context: ConversationContext,
        record_event: RecordEvent,
    ) -> None:
        self.config = config
        self.context = context
        self.record_event = record_event

    def initialize(self, state: AgentState) -> None:
        if not getattr(self.config, "enable_runtime_planning", True):
            return

        plan = build_runtime_plan(state.goal, self.config)
        state.set_plan(plan)
        self.record_event(state, "plan_created", plan.to_dict())
        self.context.add_user_message(runtime_plan_message(plan.to_dict()))
        self.mark_done(
            state,
            PlanStepKind.UNDERSTAND_TASK,
            evidence="runtime plan created from task and config",
        )
        self.mark_started(
            state,
            PlanStepKind.INSPECT_CONTEXT,
            evidence="ready to gather context",
        )

    def update_from_tool_observation(
        self,
        state: AgentState,
        action: AgentAction,
        observation: AgentObservation,
    ) -> None:
        if action.tool_name in {"read_file", "grep", "glob", "ast_context"}:
            if observation.is_error:
                self.mark_started(
                    state,
                    PlanStepKind.INSPECT_CONTEXT,
                    evidence=f"{action.tool_name} returned an error",
                )
            else:
                self.mark_done(
                    state,
                    PlanStepKind.INSPECT_CONTEXT,
                    evidence=tool_evidence(action, observation),
                )
            return

        if action.tool_name in {"write_file", "edit_file"}:
            if observation.is_error:
                self.mark_started(
                    state,
                    PlanStepKind.MODIFY_WORKSPACE,
                    evidence=f"{action.tool_name} returned an error",
                )
            else:
                self.mark_done(
                    state,
                    PlanStepKind.MODIFY_WORKSPACE,
                    evidence=tool_evidence(action, observation),
                )
            return

        if action.tool_name == "bash" and looks_like_test_command(action):
            if observation.is_error:
                self.mark_started(
                    state,
                    PlanStepKind.VERIFY_OUTCOME,
                    evidence="test-like bash command returned an error",
                )
            else:
                self.mark_done(
                    state,
                    PlanStepKind.VERIFY_OUTCOME,
                    evidence=tool_evidence(action, observation),
                )

    def update_from_verification(
        self,
        state: AgentState,
        verification_report: dict[str, Any],
    ) -> None:
        status = str(verification_report.get("status", "") or "")
        if task_constraints_passed_or_skipped(verification_report):
            self.mark_done(
                state,
                PlanStepKind.SATISFY_CONSTRAINTS,
                evidence="task constraint check passed or skipped",
            )
        elif task_constraints_failed(verification_report):
            self.mark_blocked(
                state,
                PlanStepKind.SATISFY_CONSTRAINTS,
                evidence="task constraint check failed",
            )

        if status == "passed":
            self.mark_done(
                state,
                PlanStepKind.VERIFY_OUTCOME,
                evidence=str(verification_report.get("summary", "") or "verification passed"),
            )
        elif status == "failed":
            self.mark_blocked(
                state,
                PlanStepKind.VERIFY_OUTCOME,
                evidence=str(verification_report.get("summary", "") or "verification failed"),
            )

    def complete(self, state: AgentState, *, evidence: str) -> None:
        plan = state.plan
        if plan is None:
            return
        for step in plan.steps:
            if step.status != PlanStepStatus.DONE:
                step.mark_done(evidence)
                self.record_plan_step(state, step)
        state.touch()

    def mark_started(
        self,
        state: AgentState,
        kind: PlanStepKind,
        *,
        evidence: str,
    ) -> None:
        self.set_plan_step(state, kind, PlanStepStatus.IN_PROGRESS, evidence)

    def mark_done(
        self,
        state: AgentState,
        kind: PlanStepKind,
        *,
        evidence: str,
    ) -> None:
        self.set_plan_step(state, kind, PlanStepStatus.DONE, evidence)

    def mark_blocked(
        self,
        state: AgentState,
        kind: PlanStepKind,
        *,
        evidence: str,
    ) -> None:
        self.set_plan_step(state, kind, PlanStepStatus.BLOCKED, evidence)

    def set_plan_step(
        self,
        state: AgentState,
        kind: PlanStepKind,
        status: PlanStepStatus,
        evidence: str,
    ) -> None:
        plan = state.plan
        if plan is None:
            return
        step = plan.step_by_kind(kind)
        if step is None:
            return
        if step.status == status and step.evidence == evidence:
            return
        if step.status == PlanStepStatus.DONE and status != PlanStepStatus.BLOCKED:
            return

        if status == PlanStepStatus.IN_PROGRESS:
            step.mark_started()
            step.evidence = evidence
        elif status == PlanStepStatus.DONE:
            step.mark_done(evidence)
        elif status == PlanStepStatus.BLOCKED:
            step.mark_blocked(evidence)
        else:
            step.status = status
            step.evidence = evidence
        state.touch()
        self.record_plan_step(state, step)

    def record_plan_step(self, state: AgentState, step: Any) -> None:
        self.record_event(
            state,
            "plan_step_updated",
            {
                "step": step.to_dict(),
                "plan": state.plan.to_dict() if state.plan else None,
            },
        )


def runtime_plan_message(plan: dict[str, Any]) -> str:
    steps = plan.get("steps", [])
    lines = [
        "Runtime execution plan:",
        "Use this plan as the task controller. Update your actions based on tool feedback.",
    ]
    if isinstance(steps, list):
        for step in steps[:8]:
            if not isinstance(step, dict):
                continue
            index = step.get("index", "")
            description = step.get("description", "")
            lines.append(f"{index}. {description}")
    return "\n".join(str(line) for line in lines)


def tool_evidence(action: AgentAction, observation: AgentObservation) -> str:
    path = action.tool_input.get("path")
    command = action.tool_input.get("command")
    patch = observation.metadata.get("patch")
    if isinstance(patch, dict) and patch.get("path"):
        return f"{action.tool_name} changed {patch.get('path')}"
    if path:
        return f"{action.tool_name} used path {path}"
    if command:
        return f"{action.tool_name} ran command {command}"
    return f"{action.tool_name} completed"


def looks_like_test_command(action: AgentAction) -> bool:
    command = str(action.tool_input.get("command", "")).lower()
    return any(token in command for token in ("pytest", "unittest", "npm test", "mvn test", "go test"))


def task_constraints_passed_or_skipped(report: dict[str, Any]) -> bool:
    status = task_constraint_status(report)
    return status in {"passed", "skipped"}


def task_constraints_failed(report: dict[str, Any]) -> bool:
    return task_constraint_status(report) == "failed"


def task_constraint_status(report: dict[str, Any]) -> str:
    checks = report.get("checks", [])
    if not isinstance(checks, list):
        return ""
    for check in checks:
        if not isinstance(check, dict):
            continue
        if check.get("name") == "task_constraints":
            return str(check.get("status", "") or "")
    return ""
