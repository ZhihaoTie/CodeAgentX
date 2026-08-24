"""Tests for completion-stage runtime control."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from codeagentx.agent import AgentState, CompletionController
from codeagentx.agent.planner import PlanStepKind, build_runtime_plan
from codeagentx.config import Config, PermissionMode
from codeagentx.context import ConversationContext
from codeagentx.context_engine import ContextRanker
from codeagentx.patching import PatchPolicy
from codeagentx.reflection import FailureReflector, ReflectionRetryPolicy
from codeagentx.verification import OutcomeVerifier


def python_command(code: str) -> str:
    return f'"{sys.executable}" -c "{code}"'


class CompletionControllerTests(unittest.TestCase):
    def test_successful_completion_marks_state_and_records_events(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = Config(
                model_provider="mock",
                model="mock-model",
                permission_mode=PermissionMode.AUTO,
                workspace_root=tempdir,
                verification_command=python_command("print('ok')"),
            )
            context = ConversationContext(config=config)
            state = AgentState(goal="verify")
            state.set_plan(build_runtime_plan(state.goal, config))
            events: list[tuple[str, dict]] = []

            controller = CompletionController(
                config=config,
                context=context,
                verifier=OutcomeVerifier.from_config(config),
                patch_policy=PatchPolicy.from_config(config),
                failure_reflector=FailureReflector(),
                reflection_retry_policy=ReflectionRetryPolicy(),
                context_ranker=ContextRanker.from_config(config),
                record_event=lambda _state, event_type, payload: events.append((event_type, payload)),
                mark_plan_started=lambda _state, kind, evidence: _mark_step(state, kind, "in_progress", evidence),
                mark_plan_blocked=lambda _state, kind, evidence: _mark_step(state, kind, "blocked", evidence),
                update_plan_from_verification=lambda _state, _report: None,
                complete_plan=lambda _state, evidence: _complete_plan(state, evidence),
                record_plan_step=lambda _state, _step: None,
            )

            result = controller.complete(state, "Done.")

        self.assertTrue(result.completed)
        self.assertEqual(state.status.value, "succeeded")
        self.assertEqual(state.verification_report["status"], "passed")
        self.assertIn("verification_completed", [event_type for event_type, _payload in events])
        self.assertIn("task_finished", [event_type for event_type, _payload in events])


def _mark_step(state: AgentState, kind: PlanStepKind, status: str, evidence: str) -> None:
    assert state.plan is not None
    step = state.plan.step_by_kind(kind)
    assert step is not None
    if status == "in_progress":
        step.mark_started()
        step.evidence = evidence
    elif status == "blocked":
        step.mark_blocked(evidence)


def _complete_plan(state: AgentState, evidence: str) -> None:
    assert state.plan is not None
    for step in state.plan.steps:
        step.mark_done(evidence)


if __name__ == "__main__":
    unittest.main()
