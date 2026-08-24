"""Runtime state and trajectory records for CodeAgent-X."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping
from uuid import uuid4

from .planner import TaskPlan


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class AgentAction:
    tool_name: str
    tool_input: Mapping[str, Any]
    rationale: str = ""
    action_id: str = field(default_factory=lambda: str(uuid4()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "tool_name": self.tool_name,
            "tool_input": dict(self.tool_input),
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class AgentObservation:
    tool_name: str
    output: str
    is_error: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "output": self.output,
            "is_error": self.is_error,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class TrajectoryStep:
    turn: int
    action: AgentAction
    observation: AgentObservation
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn": self.turn,
            "action": self.action.to_dict(),
            "observation": self.observation.to_dict(),
            "created_at": self.created_at,
        }


@dataclass
class AgentState:
    goal: str
    task_id: str = field(default_factory=lambda: str(uuid4()))
    status: TaskStatus = TaskStatus.PENDING
    plan: TaskPlan | None = None
    trajectory: list[TrajectoryStep] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    verification_report: Mapping[str, Any] | None = None
    patch_policy_report: Mapping[str, Any] | None = None
    rollback_report: Mapping[str, Any] | None = None
    reflection_report: Mapping[str, Any] | None = None
    plan_repair_reports: list[Mapping[str, Any]] = field(default_factory=list)
    context_ranking_reports: list[Mapping[str, Any]] = field(default_factory=list)
    reflection_retry_reports: list[Mapping[str, Any]] = field(default_factory=list)
    tool_planning_guidance_reports: list[Mapping[str, Any]] = field(default_factory=list)
    memory_retrieval_reports: list[Mapping[str, Any]] = field(default_factory=list)
    memory_extraction_reports: list[Mapping[str, Any]] = field(default_factory=list)
    run_budget_report: Mapping[str, Any] | None = None
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    failure_reason: str = ""

    @property
    def turn_index(self) -> int:
        return len(self.trajectory)

    @property
    def latest_observation(self) -> AgentObservation | None:
        if not self.trajectory:
            return None
        return self.trajectory[-1].observation

    def start(self) -> None:
        if self.status == TaskStatus.PENDING:
            self.status = TaskStatus.RUNNING
            self.touch()

    def finish(self) -> None:
        self.status = TaskStatus.SUCCEEDED
        self.touch()

    def fail(self, reason: str) -> None:
        self.status = TaskStatus.FAILED
        self.failure_reason = reason
        self.touch()

    def cancel(self, reason: str = "") -> None:
        self.status = TaskStatus.CANCELLED
        self.failure_reason = reason
        self.touch()

    def add_note(self, note: str) -> None:
        self.notes.append(note)
        self.touch()

    def set_plan(self, plan: TaskPlan) -> None:
        self.plan = plan
        self.touch()

    def set_verification_report(self, report: Mapping[str, Any]) -> None:
        self.verification_report = dict(report)
        self.touch()

    def set_patch_policy_report(self, report: Mapping[str, Any]) -> None:
        self.patch_policy_report = dict(report)
        self.touch()

    def set_rollback_report(self, report: Mapping[str, Any]) -> None:
        self.rollback_report = dict(report)
        self.touch()

    def set_reflection_report(self, report: Mapping[str, Any]) -> None:
        self.reflection_report = dict(report)
        self.touch()

    def add_plan_repair_report(self, report: Mapping[str, Any]) -> None:
        self.plan_repair_reports.append(dict(report))
        self.touch()

    def add_context_ranking_report(self, report: Mapping[str, Any]) -> None:
        self.context_ranking_reports.append(dict(report))
        self.touch()

    def add_reflection_retry_report(self, report: Mapping[str, Any]) -> None:
        self.reflection_retry_reports.append(dict(report))
        self.touch()

    def add_tool_planning_guidance_report(self, report: Mapping[str, Any]) -> None:
        self.tool_planning_guidance_reports.append(dict(report))
        self.touch()

    def add_memory_retrieval_report(self, report: Mapping[str, Any]) -> None:
        self.memory_retrieval_reports.append(dict(report))
        self.touch()

    def add_memory_extraction_report(self, report: Mapping[str, Any]) -> None:
        self.memory_extraction_reports.append(dict(report))
        self.touch()

    def set_run_budget_report(self, report: Mapping[str, Any]) -> None:
        self.run_budget_report = dict(report)
        self.touch()

    def reflection_retry_count(self) -> int:
        return sum(
            1 for report in self.reflection_retry_reports
            if report.get("status") == "retry"
        )

    def add_step(self, action: AgentAction, observation: AgentObservation) -> TrajectoryStep:
        self.start()
        step = TrajectoryStep(
            turn=self.turn_index + 1,
            action=action,
            observation=observation,
        )
        self.trajectory.append(step)
        self.touch()
        return step

    def tool_call_count(self, tool_name: str | None = None) -> int:
        if tool_name is None:
            return len(self.trajectory)
        return sum(1 for step in self.trajectory if step.action.tool_name == tool_name)

    def error_count(self) -> int:
        return sum(1 for step in self.trajectory if step.observation.is_error)

    def touch(self) -> None:
        self.updated_at = utc_now_iso()

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "goal": self.goal,
            "status": self.status.value,
            "plan": self.plan.to_dict() if self.plan else None,
            "trajectory": [step.to_dict() for step in self.trajectory],
            "notes": list(self.notes),
            "verification_report": (
                dict(self.verification_report)
                if self.verification_report is not None
                else None
            ),
            "patch_policy_report": (
                dict(self.patch_policy_report)
                if self.patch_policy_report is not None
                else None
            ),
            "rollback_report": (
                dict(self.rollback_report)
                if self.rollback_report is not None
                else None
            ),
            "reflection_report": (
                dict(self.reflection_report)
                if self.reflection_report is not None
                else None
            ),
            "plan_repair_reports": [
                dict(report) for report in self.plan_repair_reports
            ],
            "context_ranking_reports": [
                dict(report) for report in self.context_ranking_reports
            ],
            "reflection_retry_reports": [
                dict(report) for report in self.reflection_retry_reports
            ],
            "tool_planning_guidance_reports": [
                dict(report) for report in self.tool_planning_guidance_reports
            ],
            "memory_retrieval_reports": [
                dict(report) for report in self.memory_retrieval_reports
            ],
            "memory_extraction_reports": [
                dict(report) for report in self.memory_extraction_reports
            ],
            "run_budget_report": (
                dict(self.run_budget_report)
                if self.run_budget_report is not None
                else None
            ),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "failure_reason": self.failure_reason,
        }
