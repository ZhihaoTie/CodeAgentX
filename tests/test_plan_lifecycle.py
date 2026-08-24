"""Tests for runtime task plan lifecycle tracking."""

from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

from codeagentx.agent import AgentLoop, PlanStepKind
from codeagentx.config import Config, PermissionMode
from codeagentx.evaluation import analyze_state
from codeagentx.models import MockProvider, ModelResponse


def python_command(code: str) -> str:
    return f'"{sys.executable}" -c "{code}"'


class TestAgentLoopPlanLifecycle(unittest.TestCase):
    def test_runtime_plan_is_created_recorded_and_completed(self):
        provider = MockProvider([
            ModelResponse.text("Done.", model="mock-model"),
        ])

        with tempfile.TemporaryDirectory() as tempdir:
            agent = AgentLoop(
                config=Config(
                    model_provider="mock",
                    model="mock-model",
                    permission_mode=PermissionMode.AUTO,
                    trajectory_dir=tempdir,
                    verification_command=python_command("print('ok')"),
                    enable_runtime_planning=True,
                ),
                provider=provider,
            )

            with redirect_stdout(StringIO()):
                agent.run("verify the repository")

            state = agent.last_state
            self.assertIsNotNone(state)
            assert state is not None
            events = agent.trajectory_store.read_events(state.task_id)

        self.assertIsNotNone(state.plan)
        assert state.plan is not None
        metrics = analyze_state(state)
        event_types = [event["event_type"] for event in events]
        kinds = [step.kind for step in state.plan.steps]

        self.assertIn(PlanStepKind.UNDERSTAND_TASK.value, kinds)
        self.assertIn(PlanStepKind.VERIFY_OUTCOME.value, kinds)
        self.assertTrue(state.plan.is_complete())
        self.assertEqual(metrics.plan_step_count, len(state.plan.steps))
        self.assertEqual(metrics.plan_completed_steps, len(state.plan.steps))
        self.assertEqual(metrics.plan_blocked_steps, 0)
        self.assertTrue(metrics.plan_complete)
        self.assertEqual(metrics.plan_progress, 1.0)
        self.assertIn("plan_created", event_types)
        self.assertIn("plan_step_updated", event_types)
        self.assertIn("Runtime execution plan:", provider.requests[0]["messages"][-1]["content"])

    def test_runtime_planning_can_be_disabled(self):
        provider = MockProvider([
            ModelResponse.text("Done.", model="mock-model"),
        ])

        with tempfile.TemporaryDirectory() as tempdir:
            agent = AgentLoop(
                config=Config(
                    model_provider="mock",
                    model="mock-model",
                    permission_mode=PermissionMode.AUTO,
                    trajectory_dir=tempdir,
                    verification_command=python_command("print('ok')"),
                    enable_runtime_planning=False,
                ),
                provider=provider,
            )

            with redirect_stdout(StringIO()):
                agent.run("verify without runtime planning")

            state = agent.last_state
            self.assertIsNotNone(state)
            assert state is not None
            events = agent.trajectory_store.read_events(state.task_id)

        metrics = analyze_state(state)
        event_types = [event["event_type"] for event in events]

        self.assertIsNone(state.plan)
        self.assertEqual(metrics.plan_step_count, 0)
        self.assertFalse(metrics.plan_complete)
        self.assertNotIn("plan_created", event_types)


if __name__ == "__main__":
    unittest.main()
