"""Tests for reflection-driven retry behavior."""

from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from codeagentx.agent import AgentLoop
from codeagentx.config import Config, PermissionMode
from codeagentx.evaluation import analyze_state
from codeagentx.models import MockProvider, ModelResponse
from codeagentx.reflection import ReflectionRetryPolicy, ReflectionRetryStatus
from codeagentx.verification import VerificationCheck, VerificationReport, VerificationStatus


def python_command(code: str) -> str:
    return f'"{sys.executable}" -c "{code}"'


class TestReflectionRetryPolicy(unittest.TestCase):
    def test_schedules_retry_when_report_is_retryable_and_budget_remains(self):
        report = {
            "summary": "Failure reflection generated.",
            "retryable": True,
            "signals": [{
                "category": "verification_failed",
                "severity": "error",
                "message": "tests failed",
                "evidence": {"command": "python -m unittest", "exit_code": 1},
            }],
            "recommendations": ["Rerun focused tests."],
        }

        decision = ReflectionRetryPolicy().decide(
            report,
            attempted_retries=0,
            max_retries=2,
        )

        self.assertEqual(decision.status, ReflectionRetryStatus.RETRY)
        self.assertTrue(decision.should_retry)
        self.assertEqual(decision.retry_index, 1)
        self.assertIn("Retry budget: attempt 1/2", decision.prompt)
        self.assertIn("verification_failed", decision.prompt)
        self.assertIn("Retry strategy: verification_reproduction", decision.prompt)
        self.assertIsNotNone(decision.strategy)
        assert decision.strategy is not None
        self.assertEqual(decision.strategy["strategy"], "verification_reproduction")

    def test_stops_when_budget_is_exhausted(self):
        decision = ReflectionRetryPolicy().decide(
            {"summary": "failed", "retryable": True, "signals": []},
            attempted_retries=1,
            max_retries=1,
        )

        self.assertEqual(decision.status, ReflectionRetryStatus.EXHAUSTED)
        self.assertFalse(decision.should_retry)

    def test_strategy_matrix_can_be_disabled(self):
        decision = ReflectionRetryPolicy(enable_strategy_matrix=False).decide(
            {
                "summary": "Failure reflection generated.",
                "retryable": True,
                "signals": [{
                    "category": "verification_failed",
                    "severity": "error",
                    "message": "tests failed",
                    "evidence": {"exit_code": 1},
                }],
            },
            attempted_retries=0,
            max_retries=1,
        )

        self.assertEqual(decision.status, ReflectionRetryStatus.RETRY)
        self.assertIsNone(decision.strategy)
        self.assertNotIn("Retry strategy:", decision.prompt)


class TestAgentLoopReflectionRetry(unittest.TestCase):
    def test_retryable_verification_failure_can_recover(self):
        provider = MockProvider([
            ModelResponse.text("First attempt done.", model="mock-model"),
            ModelResponse.tool_use(
                tool_use_id="toolu_1",
                name="edit_file",
                tool_input={
                    "path": "app.py",
                    "old_string": "value = 1",
                    "new_string": "value = 2",
                },
                text="I will fix the value.",
                model="mock-model",
            ),
            ModelResponse.text("Fixed.", model="mock-model"),
        ])

        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "app.py"
            path.write_text("value = 1\n", encoding="utf-8")
            config = Config(
                model_provider="mock",
                model="mock-model",
                permission_mode=PermissionMode.AUTO,
                workspace_root=tempdir,
                trajectory_dir=tempdir,
                verification_command=python_command(
                    "from pathlib import Path; import sys; "
                    "sys.exit(0 if Path('app.py').read_text(encoding='utf-8').strip() == 'value = 2' else 1)"
                ),
                max_reflection_retries=1,
            )
            agent = AgentLoop(config=config, provider=provider)

            with redirect_stdout(StringIO()):
                final_text = agent.run("make app value equal 2")

            state = agent.last_state
            self.assertIsNotNone(state)
            assert state is not None
            events = agent.trajectory_store.read_events(state.task_id)
            final_content = path.read_text(encoding="utf-8")

        event_types = [event["event_type"] for event in events]
        metrics = analyze_state(state)
        retry_prompt = provider.requests[1]["messages"][-1]["content"]

        self.assertEqual(final_text, "Fixed.")
        self.assertEqual(final_content, "value = 2\n")
        self.assertEqual(state.status.value, "succeeded")
        self.assertEqual(state.reflection_retry_count(), 1)
        self.assertEqual(metrics.reflection_retry_count, 1)
        self.assertTrue(metrics.success)
        self.assertTrue(metrics.verified_success)
        self.assertIn("reflection_completed", event_types)
        self.assertIn("context_ranking_completed", event_types)
        self.assertIn("reflection_retry_scheduled", event_types)
        self.assertNotIn("task_failed", event_types)
        self.assertIn("Retry budget: attempt 1/1", retry_prompt)
        self.assertIn("Ranked context to inspect first:", retry_prompt)
        self.assertIn("Retry strategy: verification_reproduction", retry_prompt)
        self.assertIn("Strategy actions:", retry_prompt)
        self.assertGreaterEqual(metrics.context_ranking_count, 1)
        self.assertGreaterEqual(metrics.context_candidate_count, 1)
        self.assertEqual(metrics.reflection_retry_strategy, "verification_reproduction")
        self.assertIn("rerun_verification", metrics.reflection_retry_actions or [])

    def test_retry_budget_exhaustion_marks_task_failed(self):
        provider = MockProvider([
            ModelResponse.text("First attempt done.", model="mock-model"),
            ModelResponse.text("Second attempt done.", model="mock-model"),
        ])

        with tempfile.TemporaryDirectory() as tempdir:
            config = Config(
                model_provider="mock",
                model="mock-model",
                permission_mode=PermissionMode.AUTO,
                trajectory_dir=tempdir,
                verification_command=python_command("import sys; sys.exit(2)"),
                max_reflection_retries=1,
            )
            agent = AgentLoop(config=config, provider=provider)

            with redirect_stdout(StringIO()):
                agent.run("try until retry budget is exhausted")

            state = agent.last_state
            self.assertIsNotNone(state)
            assert state is not None
            events = agent.trajectory_store.read_events(state.task_id)

        event_types = [event["event_type"] for event in events]
        metrics = analyze_state(state)

        self.assertEqual(state.status.value, "failed")
        self.assertEqual(state.reflection_retry_count(), 1)
        self.assertEqual(metrics.reflection_retry_count, 1)
        self.assertEqual(metrics.reflection_retry_last_status, "exhausted")
        self.assertTrue(metrics.reflection_retry_exhausted)
        self.assertEqual(event_types.count("reflection_completed"), 2)
        self.assertIn("reflection_retry_scheduled", event_types)
        self.assertIn("reflection_retry_stopped", event_types)
        self.assertIn("task_failed", event_types)

    def test_non_retryable_reflection_does_not_retry(self):
        provider = MockProvider([
            ModelResponse.text("Done.", model="mock-model"),
            ModelResponse.text("Should not be requested.", model="mock-model"),
        ])

        with tempfile.TemporaryDirectory() as tempdir:
            config = Config(
                model_provider="mock",
                model="mock-model",
                permission_mode=PermissionMode.AUTO,
                trajectory_dir=tempdir,
                max_reflection_retries=2,
            )
            agent = AgentLoop(
                config=config,
                provider=provider,
                verifier=SandboxViolationVerifier(),
            )

            with redirect_stdout(StringIO()):
                agent.run("trigger a non-retryable sandbox violation")

            state = agent.last_state
            self.assertIsNotNone(state)
            assert state is not None
            events = agent.trajectory_store.read_events(state.task_id)

        event_types = [event["event_type"] for event in events]
        metrics = analyze_state(state)

        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(state.status.value, "failed")
        self.assertEqual(metrics.reflection_retry_count, 0)
        self.assertEqual(metrics.reflection_retry_last_status, "non_retryable")
        self.assertEqual(metrics.reflection_retry_strategy, "stop_for_intervention")
        self.assertIn("reflection_retry_stopped", event_types)
        self.assertIn("sandbox_violation", metrics.reflection_categories)


class SandboxViolationVerifier:
    def verify(self, _state, _final_text):
        return VerificationReport(
            status=VerificationStatus.FAILED,
            summary="Verification failed: sandbox violation",
            checks=[
                VerificationCheck(
                    name="verification_command",
                    status=VerificationStatus.FAILED,
                    message="Verification command violated sandbox policy: outside workspace",
                    metadata={
                        "command": "python -m unittest",
                        "cwd": "..",
                        "exit_code": None,
                        "sandbox": {
                            "sandbox_type": "local",
                            "status": "violation",
                            "timed_out": False,
                            "violation": "outside workspace",
                        },
                    },
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()
