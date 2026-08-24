"""Top-level task-run coordination for CodeAgent-X."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from codeagentx.config import Config
from codeagentx.context import ConversationContext

from .budget import RunBudget
from .completion import CompletionController
from .guidance import ToolPlanningGuidance
from .model_turn import ModelTurnController
from .plan import PlanController
from .planner import PlanStepKind
from .session import RunSession
from .state import AgentState
from .turn import TurnRunner


RecordEvent = Callable[[AgentState, str, dict[str, Any]], None]
SessionCallback = Callable[[RunSession], None]
GuidanceCallback = Callable[[ToolPlanningGuidance | None], None]
MemoryContextProvider = Callable[[AgentState, dict[str, Any] | None], dict[str, Any] | None]


@dataclass(frozen=True)
class RunResult:
    """The externally useful result of one coordinated task run."""

    final_text: str
    session: RunSession
    state: AgentState


class RunCoordinator:
    """Owns the multi-turn lifecycle of one software-engineering task."""

    def __init__(
        self,
        *,
        config: Config,
        context: ConversationContext,
        provider_name: str,
        model_turn_controller: ModelTurnController,
        turn_runner: TurnRunner,
        plan_controller: PlanController,
        completion_controller: CompletionController,
        record_event: RecordEvent,
        set_active_guidance: GuidanceCallback,
        memory_context_provider: MemoryContextProvider | None = None,
        session_callback: SessionCallback | None = None,
    ) -> None:
        self.config = config
        self.context = context
        self.provider_name = provider_name
        self.model_turn_controller = model_turn_controller
        self.turn_runner = turn_runner
        self.plan_controller = plan_controller
        self.completion_controller = completion_controller
        self.record_event = record_event
        self.set_active_guidance = set_active_guidance
        self.memory_context_provider = memory_context_provider
        self.session_callback = session_callback

    def run(self, user_message: str) -> RunResult:
        """Run one task until completion, retry exhaustion, or turn exhaustion."""

        session = RunSession(
            objective=user_message,
            config=self.config,
            provider_name=self.provider_name,
        )
        if self.session_callback is not None:
            self.session_callback(session)

        state = session.state
        budget = RunBudget.from_config(self.config)
        try:
            return self._run_session(session, user_message, budget)
        except KeyboardInterrupt:
            state.cancel("run interrupted by user")
            self.record_event(
                state,
                "task_cancelled",
                {"reason": state.failure_reason},
            )
            raise
        finally:
            report = budget.to_dict()
            state.set_run_budget_report(report)
            self.record_event(state, "run_budget_completed", report)

    def _run_session(
        self,
        session: RunSession,
        user_message: str,
        budget: RunBudget,
    ) -> RunResult:
        state = session.state
        self.set_active_guidance(None)
        self.context.add_user_message(user_message)
        final_text = ""
        self.record_event(state, "task_started", session.start_event_payload())
        self.plan_controller.initialize(state)
        self._inject_start_memory(state)

        for _turn in range(self.config.max_turns):
            budget_reason = budget.begin_turn()
            if budget_reason is not None:
                return self._fail_for_budget(
                    session,
                    state,
                    final_text,
                    budget_reason,
                    budget,
                )

            try:
                model_turn = self.model_turn_controller.run_turn()
            except Exception as exc:
                state.fail(f"model provider error: {exc}")
                self.record_event(
                    state,
                    "task_failed",
                    {
                        "error_type": exc.__class__.__name__,
                        "message": str(exc),
                    },
                )
                raise

            response = model_turn.response
            budget.record_model_usage(response.usage)
            self.record_event(state, "model_response", response.to_dict())

            if model_turn.text_parts:
                final_text = model_turn.final_text

            budget_reason = budget.limit_reason()
            if budget_reason is not None:
                return self._fail_for_budget(
                    session,
                    state,
                    final_text,
                    budget_reason,
                    budget,
                )

            if not model_turn.has_tool_calls:
                completion = self.completion_controller.complete(state, final_text)
                self.set_active_guidance(completion.active_tool_guidance)
                if completion.completed:
                    break
                final_text = ""
                continue

            tool_result = self.turn_runner.execute_tool_calls(
                model_turn.tool_calls,
                state,
            )
            budget.record_tool_calls(len(tool_result.observations))
            budget_reason = budget.limit_reason()
            if budget_reason is not None:
                return self._fail_for_budget(
                    session,
                    state,
                    final_text,
                    budget_reason,
                    budget,
                )
        else:
            if not final_text:
                final_text = "(max turns reached without a final response)"
            budget.mark_exhausted(f"max turns reached ({budget.max_turns})")
            state.fail("max turns reached without a final response")
            self.plan_controller.mark_blocked(
                state,
                PlanStepKind.FINAL_RESPONSE,
                evidence=state.failure_reason,
            )
            reflection_report = self.completion_controller.reflect_failure(
                state,
                final_text,
            )
            payload = {"reason": state.failure_reason, "final_text": final_text}
            if reflection_report is not None:
                payload["reflection_report"] = reflection_report
            self.record_event(state, "task_failed", payload)

        return RunResult(final_text=final_text, session=session, state=state)

    def _inject_start_memory(self, state: AgentState) -> None:
        if self.memory_context_provider is None:
            return
        memory_context = self.memory_context_provider(state, None)
        if memory_context is None:
            return
        prompt = str(memory_context.get("prompt", "") or "")
        if prompt:
            self.context.add_user_message(
                "Long-term memory context:\n" + prompt
            )

    def _fail_for_budget(
        self,
        session: RunSession,
        state: AgentState,
        final_text: str,
        reason: str,
        budget: RunBudget,
    ) -> RunResult:
        if not final_text:
            final_text = f"(run budget exhausted: {reason})"
        budget.mark_exhausted(reason)
        state.fail(reason)
        self.plan_controller.mark_blocked(
            state,
            PlanStepKind.FINAL_RESPONSE,
            evidence=reason,
        )
        self.record_event(
            state,
            "task_failed",
            {
                "reason": state.failure_reason,
                "final_text": final_text,
                "budget_reason": reason,
                "budget": budget.to_dict(),
            },
        )
        return RunResult(final_text=final_text, session=session, state=state)
