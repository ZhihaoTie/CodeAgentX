"""Completion, verification, and retry control for CodeAgent-X."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from codeagentx.config import Config
from codeagentx.context import ConversationContext
from codeagentx.context_engine import ContextRanker
from codeagentx.patching import PatchPolicy, rollback_applied_patches
from codeagentx.reflection import FailureReflector, ReflectionRetryPolicy
from codeagentx.verification import OutcomeVerifier

from .guidance import ToolPlanningGuidance
from .planner import PlanRepair, PlanStepKind, PlanStepStatus, build_plan_repair
from .state import AgentState


RecordEvent = Callable[[AgentState, str, dict[str, Any]], None]
MarkPlanStep = Callable[[AgentState, PlanStepKind, str], None]
UpdatePlanFromVerification = Callable[[AgentState, dict[str, Any]], None]
CompletePlan = Callable[[AgentState, str], None]
RecordPlanStep = Callable[[AgentState, Any], None]
MemoryContextProvider = Callable[[AgentState, dict[str, Any] | None], dict[str, Any] | None]
RecordSuccessMemory = Callable[[AgentState], dict[str, Any] | None]


@dataclass(frozen=True)
class CompletionResult:
    """Result of attempting to complete the task after a final model response."""

    completed: bool
    active_tool_guidance: ToolPlanningGuidance | None = None


@dataclass(frozen=True)
class RetryScheduleResult:
    """Result of reflection retry scheduling."""

    scheduled: bool
    active_tool_guidance: ToolPlanningGuidance | None = None


class CompletionController:
    """Owns verification, patch policy, rollback, reflection, and retry scheduling."""

    def __init__(
        self,
        *,
        config: Config,
        context: ConversationContext,
        verifier: OutcomeVerifier,
        patch_policy: PatchPolicy,
        failure_reflector: FailureReflector,
        reflection_retry_policy: ReflectionRetryPolicy,
        context_ranker: ContextRanker,
        record_event: RecordEvent,
        mark_plan_started: MarkPlanStep,
        mark_plan_blocked: MarkPlanStep,
        update_plan_from_verification: UpdatePlanFromVerification,
        complete_plan: CompletePlan,
        record_plan_step: RecordPlanStep,
        memory_context_provider: MemoryContextProvider | None = None,
        record_success_memory: RecordSuccessMemory | None = None,
    ) -> None:
        self.config = config
        self.context = context
        self.verifier = verifier
        self.patch_policy = patch_policy
        self.failure_reflector = failure_reflector
        self.reflection_retry_policy = reflection_retry_policy
        self.context_ranker = context_ranker
        self.record_event = record_event
        self.mark_plan_started = mark_plan_started
        self.mark_plan_blocked = mark_plan_blocked
        self.update_plan_from_verification = update_plan_from_verification
        self.complete_plan = complete_plan
        self.record_plan_step = record_plan_step
        self.memory_context_provider = memory_context_provider
        self.record_success_memory = record_success_memory

    def complete(self, state: AgentState, final_text: str) -> CompletionResult:
        self.mark_plan_started(
            state,
            PlanStepKind.VERIFY_OUTCOME,
            "model returned a final response",
        )
        try:
            report = self.verifier.verify(state, final_text)
        except Exception as exc:
            state.fail(f"outcome verifier error: {exc}")
            self.mark_plan_blocked(
                state,
                PlanStepKind.VERIFY_OUTCOME,
                state.failure_reason,
            )
            reflection_report = self.reflect_failure(state, final_text)
            payload = {
                "error_type": exc.__class__.__name__,
                "message": str(exc),
                "final_text": final_text,
            }
            if reflection_report is not None:
                payload["reflection_report"] = reflection_report
            self.record_event(state, "task_failed", payload)
            return CompletionResult(completed=True)

        report_dict = report.to_dict()
        state.set_verification_report(report_dict)
        self.record_event(state, "verification_completed", report_dict)
        self.update_plan_from_verification(state, report_dict)

        patch_policy_report = self.evaluate_patch_policy(state)
        patch_policy_failed = bool(
            patch_policy_report is not None
            and patch_policy_report.get("status") == "failed"
        )

        if report.failed or patch_policy_failed:
            rollback_report = None
            if report.failed:
                rollback_report = self.rollback_after_failed_verification(state)
            reflection_report = self.reflect_failure(state, final_text)
            retry_result = self.schedule_reflection_retry(state, reflection_report)
            if retry_result.scheduled:
                return CompletionResult(
                    completed=False,
                    active_tool_guidance=retry_result.active_tool_guidance,
                )

            failure_summary = _failure_summary(report.summary, patch_policy_report)
            state.fail(failure_summary)
            self.mark_plan_blocked(
                state,
                PlanStepKind.FINAL_RESPONSE,
                failure_summary,
            )
            payload = {
                "reason": state.failure_reason,
                "final_text": final_text,
                "verification_report": report_dict,
            }
            if patch_policy_report is not None:
                payload["patch_policy_report"] = patch_policy_report
            if rollback_report is not None:
                payload["rollback_report"] = rollback_report
            if reflection_report is not None:
                payload["reflection_report"] = reflection_report
            self.record_event(state, "task_failed", payload)
            return CompletionResult(completed=True)

        state.finish()
        self.complete_plan(state, "task finished successfully")
        memory_report = (
            self.record_success_memory(state)
            if self.record_success_memory is not None
            else None
        )
        payload = {
            "final_text": final_text,
            "verification_report": report_dict,
        }
        if memory_report is not None:
            payload["memory_extraction_report"] = memory_report
        self.record_event(
            state,
            "task_finished",
            payload,
        )
        return CompletionResult(completed=True)

    def rollback_after_failed_verification(self, state: AgentState) -> dict[str, Any] | None:
        if not getattr(self.config, "auto_rollback_on_verification_failure", False):
            return None

        patches = patch_metadata_from_state(state)
        report = rollback_applied_patches(patches).to_dict()
        state.set_rollback_report(report)
        self.record_event(state, "rollback_completed", report)
        return report

    def evaluate_patch_policy(self, state: AgentState) -> dict[str, Any] | None:
        if not getattr(self.config, "enable_patch_policy", True):
            return None

        report = self.patch_policy.evaluate(patch_metadata_from_state(state)).to_dict()
        state.set_patch_policy_report(report)
        self.record_event(state, "patch_policy_completed", report)
        return report

    def reflect_failure(
        self,
        state: AgentState,
        final_text: str,
    ) -> dict[str, Any] | None:
        if not getattr(self.config, "enable_failure_reflection", True):
            return None

        report = self.failure_reflector.reflect(state, final_text).to_dict()
        state.set_reflection_report(report)
        self.record_event(state, "reflection_completed", report)
        return report

    def schedule_reflection_retry(
        self,
        state: AgentState,
        reflection_report: dict[str, Any] | None,
    ) -> RetryScheduleResult:
        max_retries = int(getattr(self.config, "max_reflection_retries", 0) or 0)
        if max_retries <= 0:
            return RetryScheduleResult(scheduled=False)

        attempted_retries = state.reflection_retry_count()
        ranked_context_report = None
        if should_rank_retry_context(
            reflection_report,
            attempted_retries=attempted_retries,
            max_retries=max_retries,
            enabled=getattr(self.config, "enable_context_ranking", True),
        ):
            ranked_context_report = self.rank_retry_context(state, reflection_report)

        decision = self.reflection_retry_policy.decide(
            reflection_report,
            attempted_retries=attempted_retries,
            max_retries=max_retries,
            ranked_context_report=ranked_context_report,
        )
        decision_dict = decision.to_dict()

        guidance = None
        retry_prompt = decision.prompt
        if decision.should_retry and self.memory_context_provider is not None:
            memory_context = self.memory_context_provider(state, reflection_report)
            if memory_context is not None:
                report = memory_context.get("report")
                prompt_fragment = str(memory_context.get("prompt", "") or "")
                if isinstance(report, dict):
                    decision_dict["memory_retrieval_report"] = report
                retry_prompt = _append_memory_prompt(retry_prompt, prompt_fragment)

        if decision.should_retry and getattr(self.config, "enable_runtime_planning", True):
            plan_repair = build_plan_repair(
                decision_dict,
                reflection_report,
                ranked_context_report=ranked_context_report,
                config=self.config,
            )
            if plan_repair is not None:
                repair_dict = plan_repair.to_dict()
                decision_dict["plan_repair"] = repair_dict
                state.add_plan_repair_report(repair_dict)
                self.apply_plan_repair(state, plan_repair)
                retry_prompt = _append_plan_repair_prompt(retry_prompt, plan_repair)

        if decision.should_retry and getattr(self.config, "enable_tool_planning_guidance", True):
            guidance = ToolPlanningGuidance.from_retry_decision(
                decision_dict,
                reflection_report,
                config=self.config,
            )
            if guidance is not None:
                guidance_dict = guidance.to_dict()
                decision_dict["tool_planning_guidance"] = guidance_dict
                state.add_tool_planning_guidance_report(guidance_dict)
                retry_prompt = _append_guidance_prompt(retry_prompt, guidance)

        state.add_reflection_retry_report(decision_dict)

        if decision.should_retry:
            self.mark_plan_started(
                state,
                PlanStepKind.RECOVER_FAILURE,
                decision.reason,
            )
            self.record_event(state, "reflection_retry_scheduled", decision_dict)
            self.context.add_user_message(retry_prompt)
            return RetryScheduleResult(
                scheduled=True,
                active_tool_guidance=guidance,
            )

        self.mark_plan_blocked(
            state,
            PlanStepKind.RECOVER_FAILURE,
            decision.reason,
        )
        self.record_event(state, "reflection_retry_stopped", decision_dict)
        return RetryScheduleResult(scheduled=False)

    def apply_plan_repair(self, state: AgentState, repair: PlanRepair) -> None:
        plan = state.plan
        if plan is None:
            return

        target_step = plan.step_by_kind(repair.target_step_kind)
        if target_step is not None:
            target_step.status = PlanStepStatus.IN_PROGRESS
            target_step.evidence = f"plan repair strategy: {repair.strategy}"
            self.record_plan_step(state, target_step)

        for step in plan.add_steps(repair.to_plan_items()):
            self.record_plan_step(state, step)
        state.touch()
        self.record_event(state, "plan_repair_created", repair.to_dict())

    def rank_retry_context(
        self,
        state: AgentState,
        reflection_report: dict[str, Any] | None,
    ) -> dict[str, Any]:
        report = self.context_ranker.rank(
            goal=state.goal,
            reflection_report=reflection_report,
            patches=patch_metadata_from_state(state),
            limit=int(getattr(self.config, "context_ranking_limit", 6) or 6),
        ).to_dict()
        state.add_context_ranking_report(report)
        self.record_event(state, "context_ranking_completed", report)
        return report


def patch_metadata_from_state(state: AgentState) -> list[dict[str, Any]]:
    patches: list[dict[str, Any]] = []
    for step in state.trajectory:
        if step.observation.is_error:
            continue
        patch = step.observation.metadata.get("patch")
        if isinstance(patch, dict):
            patches.append(dict(patch))
    return patches


def should_rank_retry_context(
    reflection_report: dict[str, Any] | None,
    *,
    attempted_retries: int,
    max_retries: int,
    enabled: bool,
) -> bool:
    return (
        enabled
        and isinstance(reflection_report, dict)
        and bool(reflection_report.get("retryable", False))
        and attempted_retries < max_retries
    )


def _append_guidance_prompt(prompt: str, guidance: ToolPlanningGuidance) -> str:
    fragment = guidance.prompt_fragment()
    if not fragment:
        return prompt
    if not prompt:
        return "Runtime tool planning guidance:\n" + fragment
    return prompt + "\n\nRuntime tool planning guidance:\n" + fragment


def _append_plan_repair_prompt(prompt: str, repair: PlanRepair) -> str:
    fragment = repair.prompt_fragment()
    if not fragment:
        return prompt
    if not prompt:
        return "Runtime plan repair:\n" + fragment
    return prompt + "\n\nRuntime plan repair:\n" + fragment


def _append_memory_prompt(prompt: str, fragment: str) -> str:
    if not fragment:
        return prompt
    if not prompt:
        return "Long-term memory context:\n" + fragment
    return prompt + "\n\nLong-term memory context:\n" + fragment


def _failure_summary(
    verification_summary: str,
    patch_policy_report: dict[str, Any] | None,
) -> str:
    if patch_policy_report and patch_policy_report.get("status") == "failed":
        policy_summary = str(patch_policy_report.get("summary") or "Patch policy failed.")
        if verification_summary.startswith("Verification failed"):
            return f"{verification_summary}; {policy_summary}"
        return policy_summary
    return verification_summary
