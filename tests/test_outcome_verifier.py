"""Tests for explicit outcome verification."""

from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from codeagentx.agent import AgentLoop, AgentState
from codeagentx.config import Config, PermissionMode
from codeagentx.evaluation import analyze_state
from codeagentx.models import MockProvider, ModelResponse
from codeagentx.verification import OutcomeVerifier, VerificationStatus


def python_command(code: str) -> str:
    return f'"{sys.executable}" -c "{code}"'


class TestOutcomeVerifier(unittest.TestCase):
    def test_skips_when_no_command_is_configured(self):
        state = AgentState(goal="inspect repo")
        state.start()
        verifier = OutcomeVerifier(command=None)

        report = verifier.verify(state, "Done.")

        self.assertEqual(report.status, VerificationStatus.SKIPPED)
        self.assertTrue(report.skipped)
        self.assertEqual(report.checks[-1].name, "verification_command")

    def test_fails_empty_final_response_even_without_command(self):
        state = AgentState(goal="inspect repo")
        verifier = OutcomeVerifier(command=None)

        report = verifier.verify(state, "")

        self.assertEqual(report.status, VerificationStatus.FAILED)
        self.assertIn("without final text", report.summary)

    def test_passes_when_verification_command_exits_zero(self):
        state = AgentState(goal="run tests")
        verifier = OutcomeVerifier(command=python_command("print('ok')"))

        report = verifier.verify(state, "Done.")

        self.assertEqual(report.status, VerificationStatus.PASSED)
        command_check = report.checks[-1]
        self.assertEqual(command_check.metadata["exit_code"], 0)
        self.assertIn("ok", command_check.metadata["stdout"])
        self.assertEqual(command_check.metadata["sandbox"]["sandbox_type"], "local")
        self.assertEqual(command_check.metadata["sandbox"]["status"], "passed")
        self.assertEqual(command_check.metadata["test_result"]["framework"], "unknown")

    def test_fails_when_verification_command_exits_nonzero(self):
        state = AgentState(goal="run tests")
        verifier = OutcomeVerifier(command=python_command("import sys; sys.exit(3)"))

        report = verifier.verify(state, "Done.")

        self.assertEqual(report.status, VerificationStatus.FAILED)
        self.assertIn("code 3", report.summary)

    def test_records_structured_unittest_result(self):
        state = AgentState(goal="run tests")
        verifier = OutcomeVerifier(
            command=python_command(
                "import sys; "
                "sys.stderr.write('Ran 2 tests in 0.001s\\n\\nOK\\n')"
            )
        )

        report = verifier.verify(state, "Done.")
        command_check = report.checks[-1]

        self.assertEqual(report.status, VerificationStatus.PASSED)
        self.assertEqual(command_check.metadata["test_result"]["framework"], "unittest")
        self.assertEqual(command_check.metadata["test_result"]["total"], 2)
        self.assertEqual(command_check.metadata["test_result"]["passed"], 2)

    def test_writes_verification_artifacts_when_configured(self):
        with tempfile.TemporaryDirectory() as tempdir:
            state = AgentState(goal="run tests")
            state.start()
            Path(tempdir, "app.py").write_text("print('hi')\n", encoding="utf-8")
            verifier = OutcomeVerifier(
                command=python_command("print('artifact-ok')"),
                cwd=tempdir,
                sandbox_artifact_dir=Path(tempdir) / "artifacts",
            )

            report = verifier.verify(state, "Done.")

            state.set_verification_report(report.to_dict())
            command_check = report.checks[-1]
            artifacts = command_check.metadata["artifacts"]
            metrics = analyze_state(state)

            self.assertEqual(report.status, VerificationStatus.PASSED)
            self.assertEqual(artifacts["kind"], "verification")
            self.assertTrue(Path(artifacts["stdout_path"]).exists())
            self.assertIn("artifact-ok", Path(artifacts["stdout_path"]).read_text(encoding="utf-8"))
            self.assertEqual(artifacts["workspace_snapshot"]["fingerprinted_files"], 1)
            self.assertEqual(metrics.verification_artifact_count, 1)
            self.assertEqual(metrics.verification_workspace_file_count, 1)
            self.assertIsNotNone(metrics.verification_workspace_sha256)


class TestAgentLoopOutcomeVerification(unittest.TestCase):
    def test_successful_verification_marks_state_succeeded(self):
        provider = MockProvider([ModelResponse.text("Done.", model="mock-model")])

        with tempfile.TemporaryDirectory() as tempdir:
            config = Config(
                model_provider="mock",
                model="mock-model",
                permission_mode=PermissionMode.AUTO,
                trajectory_dir=tempdir,
                verification_command=python_command("print('verified')"),
            )
            agent = AgentLoop(config=config, provider=provider)

            with redirect_stdout(StringIO()):
                agent.run("verify success")

            state = agent.last_state
            self.assertIsNotNone(state)
            assert state is not None
            events = agent.trajectory_store.read_events(state.task_id)
            snapshot = agent.trajectory_store.load_state(state.task_id)

        event_types = [event["event_type"] for event in events]
        metrics = analyze_state(state)

        self.assertEqual(state.status.value, "succeeded")
        self.assertEqual(state.verification_report["status"], "passed")
        self.assertEqual(snapshot["state"]["verification_report"]["status"], "passed")
        self.assertIn("verification_completed", event_types)
        self.assertIn("task_finished", event_types)
        self.assertTrue(metrics.verified_success)
        self.assertIsNone(metrics.structured_tests_total)
        self.assertEqual(metrics.verification_sandbox_type, "local")
        self.assertEqual(metrics.verification_sandbox_status, "passed")

    def test_structured_test_result_flows_into_metrics(self):
        provider = MockProvider([ModelResponse.text("Done.", model="mock-model")])

        with tempfile.TemporaryDirectory() as tempdir:
            config = Config(
                model_provider="mock",
                model="mock-model",
                permission_mode=PermissionMode.AUTO,
                trajectory_dir=tempdir,
                verification_command=python_command(
                    "import sys; "
                    "sys.stderr.write('Ran 3 tests in 0.002s\\n\\nOK\\n')"
                ),
            )
            agent = AgentLoop(config=config, provider=provider)

            with redirect_stdout(StringIO()):
                agent.run("verify structured tests")

            state = agent.last_state
            self.assertIsNotNone(state)
            assert state is not None

        metrics = analyze_state(state)

        self.assertEqual(metrics.structured_tests_total, 3)
        self.assertEqual(metrics.structured_tests_passed, 3)
        self.assertEqual(metrics.structured_tests_failed, 0)

    def test_failed_verification_marks_state_failed(self):
        provider = MockProvider([ModelResponse.text("Done.", model="mock-model")])

        with tempfile.TemporaryDirectory() as tempdir:
            config = Config(
                model_provider="mock",
                model="mock-model",
                permission_mode=PermissionMode.AUTO,
                trajectory_dir=tempdir,
                verification_command=python_command("import sys; sys.exit(2)"),
            )
            agent = AgentLoop(config=config, provider=provider)

            with redirect_stdout(StringIO()):
                final_text = agent.run("verify failure")

            state = agent.last_state
            self.assertIsNotNone(state)
            assert state is not None
            events = agent.trajectory_store.read_events(state.task_id)
            snapshot = agent.trajectory_store.load_state(state.task_id)

        event_types = [event["event_type"] for event in events]
        metrics = analyze_state(state)

        self.assertEqual(final_text, "Done.")
        self.assertEqual(state.status.value, "failed")
        self.assertEqual(state.verification_report["status"], "failed")
        self.assertEqual(state.reflection_report["status"], "generated")
        self.assertEqual(snapshot["state"]["status"], "failed")
        self.assertEqual(snapshot["state"]["reflection_report"]["status"], "generated")
        self.assertIn("verification_completed", event_types)
        self.assertIn("reflection_completed", event_types)
        self.assertIn("task_failed", event_types)
        self.assertFalse(metrics.success)
        self.assertFalse(metrics.verified_success)
        self.assertEqual(metrics.verification_sandbox_status, "failed")
        self.assertEqual(metrics.reflection_status, "generated")
        self.assertTrue(metrics.reflection_retryable)
        self.assertIn("verification_failed", metrics.reflection_categories)

    def test_auto_rollback_restores_patch_when_verification_fails(self):
        provider = MockProvider([
            ModelResponse.tool_use(
                tool_use_id="toolu_1",
                name="edit_file",
                tool_input={
                    "path": "app.py",
                    "old_string": "value = 1",
                    "new_string": "value = 2",
                },
                text="I will edit the file.",
                model="mock-model",
            ),
            ModelResponse.text("Done.", model="mock-model"),
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
                verification_command=python_command("import sys; sys.exit(2)"),
                auto_rollback_on_verification_failure=True,
            )
            agent = AgentLoop(config=config, provider=provider)

            with redirect_stdout(StringIO()):
                agent.run("edit and rollback")

            state = agent.last_state
            self.assertIsNotNone(state)
            assert state is not None
            events = agent.trajectory_store.read_events(state.task_id)
            snapshot = agent.trajectory_store.load_state(state.task_id)
            final_content = path.read_text(encoding="utf-8")

        event_types = [event["event_type"] for event in events]
        metrics = analyze_state(state)

        self.assertEqual(final_content, "value = 1\n")
        self.assertEqual(state.status.value, "failed")
        self.assertEqual(state.rollback_report["status"], "passed")
        self.assertEqual(snapshot["state"]["rollback_report"]["attempted"], 1)
        self.assertIn("rollback_completed", event_types)
        self.assertEqual(metrics.rollback_attempted, 1)
        self.assertEqual(metrics.rollback_restored, 1)
        self.assertEqual(metrics.rollback_failed, 0)

    def test_failed_verification_keeps_patch_when_auto_rollback_disabled(self):
        provider = MockProvider([
            ModelResponse.tool_use(
                tool_use_id="toolu_1",
                name="write_file",
                tool_input={"path": "generated.txt", "content": "broken\n"},
                text="I will write the file.",
                model="mock-model",
            ),
            ModelResponse.text("Done.", model="mock-model"),
        ])

        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "generated.txt"
            config = Config(
                model_provider="mock",
                model="mock-model",
                permission_mode=PermissionMode.AUTO,
                workspace_root=tempdir,
                trajectory_dir=tempdir,
                verification_command=python_command("import sys; sys.exit(2)"),
            )
            agent = AgentLoop(config=config, provider=provider)

            with redirect_stdout(StringIO()):
                agent.run("edit without rollback")

            state = agent.last_state
            self.assertIsNotNone(state)
            assert state is not None
            events = agent.trajectory_store.read_events(state.task_id)
            final_content = path.read_text(encoding="utf-8")

        event_types = [event["event_type"] for event in events]

        self.assertEqual(final_content, "broken\n")
        self.assertIsNone(state.rollback_report)
        self.assertNotIn("rollback_completed", event_types)

    def test_failure_reflection_can_be_disabled(self):
        provider = MockProvider([ModelResponse.text("Done.", model="mock-model")])

        with tempfile.TemporaryDirectory() as tempdir:
            config = Config(
                model_provider="mock",
                model="mock-model",
                permission_mode=PermissionMode.AUTO,
                trajectory_dir=tempdir,
                verification_command=python_command("import sys; sys.exit(2)"),
                enable_failure_reflection=False,
            )
            agent = AgentLoop(config=config, provider=provider)

            with redirect_stdout(StringIO()):
                agent.run("verify failure without reflection")

            state = agent.last_state
            self.assertIsNotNone(state)
            assert state is not None
            events = agent.trajectory_store.read_events(state.task_id)

        event_types = [event["event_type"] for event in events]

        self.assertEqual(state.status.value, "failed")
        self.assertIsNone(state.reflection_report)
        self.assertNotIn("reflection_completed", event_types)


if __name__ == "__main__":
    unittest.main()
