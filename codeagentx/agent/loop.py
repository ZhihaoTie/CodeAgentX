"""Agent loop for CodeAgent-X.

The loop follows the standard autonomous SWE agent rhythm:

1. Send the current task context and tool schemas to the model.
2. Parse text and tool_use blocks from the model response.
3. Execute tool calls through the permission-aware ToolExecutor.
4. Record every action and observation into AgentState.
5. Feed tool results back into the model until it returns a final answer.
6. Verify the final outcome before marking the task as succeeded.
"""

from __future__ import annotations

from typing import Any

from ..config import Config, load_env_file
from ..context import ConversationContext
from ..context_engine import ContextRanker
from ..memory import MemoryExtractor, MemoryRetriever, MemoryStore, format_memory_prompt
from ..models import ModelProvider, ModelResponse, create_model_provider
from ..patching import PatchPolicy
from ..permissions import PermissionGate
from ..reflection import FailureReflector, ReflectionRetryPolicy
from ..storage import TrajectoryStore
from ..system_prompt import build_system_prompt
from ..tools.base import ToolRegistry
from ..verification import OutcomeVerifier
from .completion import CompletionController, patch_metadata_from_state, should_rank_retry_context
from .coordinator import RunCoordinator
from .executor import ToolExecutor
from .guidance import ToolGuidanceCheck, ToolPlanningGuidance
from .guidance_controller import ToolGuidanceController
from .model_turn import ModelTurnController
from .plan import (
    PlanController,
    looks_like_test_command,
    runtime_plan_message,
    task_constraint_status,
    task_constraints_failed,
    task_constraints_passed_or_skipped,
    tool_evidence,
)
from .planner import PlanStepKind, PlanStepStatus
from .session import RunSession
from .state import AgentAction, AgentObservation, AgentState
from .trajectory import TrajectoryRecorder
from .turn import TurnRunner


class AgentLoop:
    """The core software-engineering agent loop.

    Runtime state and trajectory are first-class so evaluation can analyze real
    tool behavior instead of reconstructing it from console logs.
    """

    def __init__(
        self,
        config: Config | None = None,
        registry: ToolRegistry | None = None,
        provider: ModelProvider | None = None,
        trajectory_store: TrajectoryStore | None = None,
        verifier: OutcomeVerifier | None = None,
    ) -> None:
        load_env_file()
        self.config = config if config is not None else Config.from_env()
        self.registry = registry or ToolRegistry.default()
        self.permission_gate = PermissionGate(self.config)
        self.tool_executor = ToolExecutor(
            registry=self.registry,
            config=self.config,
            permission_gate=self.permission_gate,
        )
        self.context = ConversationContext(config=self.config)
        self.context_ranker = ContextRanker.from_config(self.config)
        self.memory_store = self._create_memory_store()
        self.memory_retriever = self._create_memory_retriever()
        self.memory_extractor = MemoryExtractor()
        self.provider = provider or create_model_provider(self.config)
        self.trajectory_store = trajectory_store
        if self.trajectory_store is None and self.config.trajectory_dir:
            self.trajectory_store = TrajectoryStore(self.config.trajectory_dir)
        self.trajectory_recorder = self._create_trajectory_recorder()
        self.verifier = verifier or OutcomeVerifier.from_config(self.config)
        self.patch_policy = PatchPolicy.from_config(self.config)
        self.failure_reflector = FailureReflector()
        self.reflection_retry_policy = ReflectionRetryPolicy(
            max_prompt_chars=self.config.reflection_retry_prompt_max_chars,
            enable_strategy_matrix=getattr(self.config, "enable_retry_strategy_matrix", True),
        )
        self.active_tool_guidance: ToolPlanningGuidance | None = None
        self.guidance_controller = self._create_guidance_controller()
        self.last_session: RunSession | None = None
        self.last_state: AgentState | None = None
        self.model_turn_controller = self._create_model_turn_controller()
        self.turn_runner = self._create_turn_runner()
        self.plan_controller = self._create_plan_controller()
        self.completion_controller = self._create_completion_controller()

        self._set_system_prompt()

    def run(self, user_message: str) -> str:
        """Process a user message through the agent loop."""
        self._reset_run_runtime()
        result = self._get_run_coordinator().run(user_message)
        self.last_session = result.session
        self.last_state = result.state
        return result.final_text

    def _reset_run_runtime(self) -> None:
        """Start each public run with an isolated conversation and controllers."""

        self.context = ConversationContext(config=self.config)
        self._set_system_prompt()
        self.active_tool_guidance = None
        self.context_ranker = ContextRanker.from_config(self.config)
        self.memory_store = self._create_memory_store()
        self.memory_retriever = self._create_memory_retriever()
        self.memory_extractor = MemoryExtractor()
        self.reflection_retry_policy = ReflectionRetryPolicy(
            max_prompt_chars=self.config.reflection_retry_prompt_max_chars,
            enable_strategy_matrix=getattr(self.config, "enable_retry_strategy_matrix", True),
        )
        self.guidance_controller = self._create_guidance_controller()
        self.model_turn_controller = self._create_model_turn_controller()
        self.turn_runner = self._create_turn_runner()
        self.plan_controller = self._create_plan_controller()
        self.completion_controller = self._create_completion_controller()
        self.run_coordinator = self._create_run_coordinator()

    def _set_system_prompt(self) -> None:
        system_prompt = build_system_prompt(
            self.registry,
            permission_mode=self.config.permission_mode.value,
            workspace_root=self.config.workspace_root,
            verification_command=self.config.verification_command,
        )
        self.context.set_system_prompt(system_prompt)

    def _call_api(self) -> ModelResponse:
        """Call the configured model provider with current context."""
        return self._get_model_turn_controller().call_api()

    def _parse_response(self, response: ModelResponse) -> tuple[list[dict], list[str]]:
        """Extract tool_use blocks and text blocks from the API response."""
        turn = self._get_model_turn_controller().parse_response(response)
        return turn.tool_calls, turn.text_parts

    def _create_model_turn_controller(self) -> ModelTurnController:
        return ModelTurnController(
            config=self.config,
            context=self.context,
            provider=self.provider,
            registry=self.registry,
        )

    def _get_model_turn_controller(self) -> ModelTurnController:
        controller = getattr(self, "model_turn_controller", None)
        if controller is None:
            controller = self._create_model_turn_controller()
            self.model_turn_controller = controller
        return controller

    def _execute_tool_calls(self, tool_calls: list[dict], state: AgentState) -> None:
        """Execute tool calls through the turn runner."""
        self._get_turn_runner().execute_tool_calls(tool_calls, state)

    def _create_turn_runner(self) -> TurnRunner:
        return TurnRunner(
            tool_executor=self.tool_executor,
            context=self.context,
            guidance_callback=self._check_tool_guidance,
            observation_callback=self._record_tool_observation,
        )

    def _get_turn_runner(self) -> TurnRunner:
        runner = getattr(self, "turn_runner", None)
        if runner is None:
            runner = self._create_turn_runner()
            self.turn_runner = runner
        return runner

    def _record_tool_observation(
        self,
        state: AgentState,
        action: AgentAction,
        observation: AgentObservation,
    ) -> None:
        self._update_plan_from_tool_observation(state, action, observation)
        self._record_trajectory(
            state,
            "tool_observation",
            {
                "action": action.to_dict(),
                "observation": observation.to_dict(),
            },
        )

    def _complete_with_verification(self, state: AgentState, final_text: str) -> bool:
        result = self._get_completion_controller().complete(state, final_text)
        self._set_active_tool_guidance(result.active_tool_guidance)
        return result.completed

    def _record_trajectory(
        self,
        state: AgentState,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        self._get_trajectory_recorder().record(state, event_type, payload)

    def _create_trajectory_recorder(self) -> TrajectoryRecorder:
        return TrajectoryRecorder(getattr(self, "trajectory_store", None))

    def _create_memory_store(self) -> MemoryStore | None:
        if not getattr(self.config, "enable_long_term_memory", False):
            return None
        path = getattr(self.config, "memory_store_path", None)
        if not path:
            return None
        return MemoryStore(path)

    def _create_memory_retriever(self) -> MemoryRetriever | None:
        store = getattr(self, "memory_store", None)
        if store is None:
            return None
        return MemoryRetriever(
            store,
            default_limit=int(getattr(self.config, "memory_retrieval_limit", 3) or 3),
            default_min_score=int(getattr(self.config, "memory_min_score", 0) or 0),
        )

    def _retrieve_memory_context(
        self,
        state: AgentState,
        reflection_report: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        retriever = getattr(self, "memory_retriever", None)
        if retriever is None:
            return None

        report = retriever.retrieve(
            goal=state.goal,
            reflection_report=reflection_report,
            patches=patch_metadata_from_state(state),
            limit=int(getattr(self.config, "memory_retrieval_limit", 3) or 3),
            min_score=int(getattr(self.config, "memory_min_score", 0) or 0),
        )
        report_dict = report.to_dict()
        prompt = format_memory_prompt(
            report_dict,
            max_chars=int(getattr(self.config, "memory_prompt_max_chars", 2_500) or 2_500),
            limit=int(getattr(self.config, "memory_retrieval_limit", 3) or 3),
        )
        report_dict["prompt_injected"] = bool(prompt)
        if not prompt and report_dict.get("status") == "filtered":
            report_dict["skip_reason"] = report_dict.get("summary")
        state.add_memory_retrieval_report(report_dict)
        self._record_trajectory(state, "memory_retrieved", report_dict)
        return {
            "report": report_dict,
            "prompt": prompt,
        }

    def _record_success_memory(self, state: AgentState) -> dict[str, Any] | None:
        store = getattr(self, "memory_store", None)
        extractor = getattr(self, "memory_extractor", None)
        if store is None or extractor is None:
            return None

        evidence_path = ""
        trajectory_store = getattr(self, "trajectory_store", None)
        if trajectory_store is not None:
            evidence_path = str(trajectory_store.events_path(state.task_id))
        record = extractor.extract(
            state,
            evidence_path=evidence_path,
            workspace_root=getattr(self.config, "workspace_root", None),
        )
        if record is None:
            report = {
                "status": "skipped",
                "reason": "state was not a verified successful trajectory",
            }
            state.add_memory_extraction_report(report)
            self._record_trajectory(state, "memory_extracted", report)
            return report

        added, path = store.append_if_new(record)
        report = {
            "status": "stored" if added else "duplicate",
            "memory_id": record.memory_id,
            "store_path": str(path or store.path),
            "record": record.to_dict(),
        }
        state.add_memory_extraction_report(report)
        self._record_trajectory(state, "memory_extracted", report)
        return report

    def _get_trajectory_recorder(self) -> TrajectoryRecorder:
        recorder = getattr(self, "trajectory_recorder", None)
        if recorder is None:
            recorder = self._create_trajectory_recorder()
            self.trajectory_recorder = recorder
        return recorder

    def _rollback_after_failed_verification(self, state: AgentState) -> dict[str, Any] | None:
        return self._get_completion_controller().rollback_after_failed_verification(state)

    def _evaluate_patch_policy(self, state: AgentState) -> dict[str, Any] | None:
        return self._get_completion_controller().evaluate_patch_policy(state)

    def _reflect_failure(self, state: AgentState, final_text: str) -> dict[str, Any] | None:
        return self._get_completion_controller().reflect_failure(state, final_text)

    def _schedule_reflection_retry(
        self,
        state: AgentState,
        reflection_report: dict[str, Any] | None,
    ) -> bool:
        result = self._get_completion_controller().schedule_reflection_retry(
            state,
            reflection_report,
        )
        self._set_active_tool_guidance(result.active_tool_guidance)
        return result.scheduled

    def _check_tool_guidance(
        self,
        state: AgentState,
        action: AgentAction,
    ) -> ToolGuidanceCheck | None:
        controller = self._get_guidance_controller()
        compatibility_guidance = getattr(self, "active_tool_guidance", None)
        if compatibility_guidance is not controller.active_guidance:
            controller.set_guidance(compatibility_guidance)
        return controller.check(state, action)

    def _set_active_tool_guidance(
        self,
        guidance: ToolPlanningGuidance | None,
    ) -> None:
        self.active_tool_guidance = guidance
        self._get_guidance_controller().set_guidance(guidance)

    def _create_guidance_controller(self) -> ToolGuidanceController:
        return ToolGuidanceController(
            record_event=self._get_trajectory_recorder().record,
            active_guidance=getattr(self, "active_tool_guidance", None),
        )

    def _get_guidance_controller(self) -> ToolGuidanceController:
        controller = getattr(self, "guidance_controller", None)
        if controller is None:
            controller = self._create_guidance_controller()
            self.guidance_controller = controller
        return controller

    def _initialize_plan(self, state: AgentState) -> None:
        self._get_plan_controller().initialize(state)

    def _update_plan_from_tool_observation(
        self,
        state: AgentState,
        action: AgentAction,
        observation: AgentObservation,
    ) -> None:
        self._get_plan_controller().update_from_tool_observation(
            state,
            action,
            observation,
        )

    def _update_plan_from_verification(
        self,
        state: AgentState,
        verification_report: dict[str, Any],
    ) -> None:
        self._get_plan_controller().update_from_verification(
            state,
            verification_report,
        )

    def _complete_plan(self, state: AgentState, *, evidence: str) -> None:
        self._get_plan_controller().complete(state, evidence=evidence)

    def _mark_plan_started(
        self,
        state: AgentState,
        kind: PlanStepKind,
        *,
        evidence: str,
    ) -> None:
        self._get_plan_controller().mark_started(state, kind, evidence=evidence)

    def _mark_plan_done(
        self,
        state: AgentState,
        kind: PlanStepKind,
        *,
        evidence: str,
    ) -> None:
        self._get_plan_controller().mark_done(state, kind, evidence=evidence)

    def _mark_plan_blocked(
        self,
        state: AgentState,
        kind: PlanStepKind,
        *,
        evidence: str,
    ) -> None:
        self._get_plan_controller().mark_blocked(state, kind, evidence=evidence)

    def _set_plan_step(
        self,
        state: AgentState,
        kind: PlanStepKind,
        status: PlanStepStatus,
        evidence: str,
    ) -> None:
        self._get_plan_controller().set_plan_step(state, kind, status, evidence)

    def _record_plan_step(self, state: AgentState, step: Any) -> None:
        self._get_plan_controller().record_plan_step(state, step)

    def _create_plan_controller(self) -> PlanController:
        return PlanController(
            config=getattr(self, "config", self.context.config),
            context=self.context,
            record_event=self._get_trajectory_recorder().record,
        )

    def _get_plan_controller(self) -> PlanController:
        controller = getattr(self, "plan_controller", None)
        if controller is None:
            controller = self._create_plan_controller()
            self.plan_controller = controller
        return controller

    def _rank_retry_context(
        self,
        state: AgentState,
        reflection_report: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return self._get_completion_controller().rank_retry_context(state, reflection_report)

    def _create_completion_controller(self) -> CompletionController:
        return CompletionController(
            config=self.config,
            context=self.context,
            verifier=self.verifier,
            patch_policy=self.patch_policy,
            failure_reflector=self.failure_reflector,
            reflection_retry_policy=self.reflection_retry_policy,
            context_ranker=self.context_ranker,
            record_event=self._get_trajectory_recorder().record,
            mark_plan_started=lambda state, kind, evidence: self._get_plan_controller().mark_started(
                state,
                kind,
                evidence=evidence,
            ),
            mark_plan_blocked=lambda state, kind, evidence: self._get_plan_controller().mark_blocked(
                state,
                kind,
                evidence=evidence,
            ),
            update_plan_from_verification=self._get_plan_controller().update_from_verification,
            complete_plan=lambda state, evidence: self._get_plan_controller().complete(
                state,
                evidence=evidence,
            ),
            record_plan_step=self._get_plan_controller().record_plan_step,
            memory_context_provider=self._retrieve_memory_context,
            record_success_memory=self._record_success_memory,
        )

    def _get_completion_controller(self) -> CompletionController:
        controller = getattr(self, "completion_controller", None)
        if controller is None:
            controller = self._create_completion_controller()
            self.completion_controller = controller
        return controller

    def _on_session_started(self, session: RunSession) -> None:
        self.last_session = session
        self.last_state = session.state

    def _create_run_coordinator(self) -> RunCoordinator:
        return RunCoordinator(
            config=self.config,
            context=self.context,
            provider_name=self.provider.name,
            model_turn_controller=self._get_model_turn_controller(),
            turn_runner=self._get_turn_runner(),
            plan_controller=self._get_plan_controller(),
            completion_controller=self._get_completion_controller(),
            record_event=self._get_trajectory_recorder().record,
            set_active_guidance=self._set_active_tool_guidance,
            memory_context_provider=self._retrieve_memory_context,
            session_callback=self._on_session_started,
        )

    def _get_run_coordinator(self) -> RunCoordinator:
        coordinator = getattr(self, "run_coordinator", None)
        if coordinator is None:
            coordinator = self._create_run_coordinator()
            self.run_coordinator = coordinator
        return coordinator


def _runtime_plan_message(plan: dict[str, Any]) -> str:
    return runtime_plan_message(plan)


def _tool_evidence(action: AgentAction, observation: AgentObservation) -> str:
    return tool_evidence(action, observation)


def _looks_like_test_command(action: AgentAction) -> bool:
    return looks_like_test_command(action)


def _task_constraints_passed_or_skipped(report: dict[str, Any]) -> bool:
    return task_constraints_passed_or_skipped(report)


def _task_constraints_failed(report: dict[str, Any]) -> bool:
    return task_constraints_failed(report)


def _task_constraint_status(report: dict[str, Any]) -> str:
    return task_constraint_status(report)


def _patch_metadata_from_state(state: AgentState) -> list[dict[str, Any]]:
    return patch_metadata_from_state(state)


def _should_rank_retry_context(
    reflection_report: dict[str, Any] | None,
    *,
    attempted_retries: int,
    max_retries: int,
    enabled: bool,
) -> bool:
    return should_rank_retry_context(
        reflection_report,
        attempted_retries=attempted_retries,
        max_retries=max_retries,
        enabled=enabled,
    )
