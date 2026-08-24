"""Tests for deterministic task constraint verification."""

from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from codeagentx.agent import AgentAction, AgentLoop, AgentObservation, AgentState
from codeagentx.config import Config, PermissionMode
from codeagentx.evaluation import analyze_state
from codeagentx.models import MockProvider, ModelResponse
from codeagentx.verification import (
    OutcomeVerifier,
    TaskConstraintSpec,
    TaskConstraintVerifier,
    VerificationStatus,
)


def python_command(code: str) -> str:
    return f'"{sys.executable}" -c "{code}"'


def state_with_patch(workspace: str, relative_path: str) -> AgentState:
    state = AgentState(goal="verify constraints")
    path = Path(workspace) / relative_path
    state.add_step(
        AgentAction(tool_name="write_file", tool_input={"path": relative_path}),
        AgentObservation(
            tool_name="write_file",
            output="wrote file",
            metadata={"patch": {"path": str(path)}},
        ),
    )
    return state


class TestTaskConstraintVerifier(unittest.TestCase):
    def test_passes_required_and_forbidden_path_constraints(self):
        with tempfile.TemporaryDirectory() as tempdir:
            state = state_with_patch(tempdir, "src/app.py")
            verifier = TaskConstraintVerifier(
                TaskConstraintSpec(
                    required_changed_paths=["src/*.py"],
                    forbidden_changed_paths=["docs/*"],
                    required_final_response_substrings=["Done"],
                ),
                workspace_root=tempdir,
            )

            result = verifier.verify(state, "Done.")

        self.assertTrue(result.passed)
        self.assertEqual(result.metadata["violation_count"], 0)
        self.assertEqual(result.metadata["changed_paths"], ["src/app.py"])

    def test_fails_missing_required_and_modified_forbidden_paths(self):
        with tempfile.TemporaryDirectory() as tempdir:
            state = state_with_patch(tempdir, "docs/notes.md")
            verifier = TaskConstraintVerifier(
                TaskConstraintSpec(
                    required_changed_paths=["src/*.py"],
                    forbidden_changed_paths=["docs/*"],
                    forbidden_final_response_substrings=["not fixed"],
                ),
                workspace_root=tempdir,
            )

            result = verifier.verify(state, "Done, but not fixed.")

        self.assertTrue(result.failed)
        self.assertEqual(result.metadata["violation_count"], 3)
        violation_types = {item["type"] for item in result.metadata["violations"]}
        self.assertIn("required_changed_path_missing", violation_types)
        self.assertIn("forbidden_changed_path_modified", violation_types)
        self.assertIn("forbidden_final_response_present", violation_types)

    def test_success_criteria_only_are_audit_metadata(self):
        state = AgentState(goal="audit success criteria")
        verifier = TaskConstraintVerifier(
            TaskConstraintSpec(success_criteria=["Tests pass", "No forbidden files touched"]),
        )

        result = verifier.verify(state, "Done.")

        self.assertTrue(result.skipped)
        self.assertFalse(result.metadata["deterministic"])
        self.assertEqual(len(result.metadata["success_criteria"]), 2)

    def test_relative_patch_paths_are_resolved_from_workspace_root(self):
        state = AgentState(goal="verify relative patch paths")
        state.add_step(
            AgentAction(tool_name="edit_file", tool_input={"path": "src/app.py"}),
            AgentObservation(
                tool_name="edit_file",
                output="edited file",
                metadata={"patch": {"path": "src/app.py"}},
            ),
        )
        with tempfile.TemporaryDirectory() as tempdir:
            verifier = TaskConstraintVerifier(
                TaskConstraintSpec(required_changed_paths=["src/app.py"]),
                workspace_root=tempdir,
            )

            result = verifier.verify(state, "Done.")

        self.assertTrue(result.passed)
        self.assertEqual(result.metadata["changed_paths"], ["src/app.py"])


class TestOutcomeVerifierTaskConstraints(unittest.TestCase):
    def test_constraints_can_pass_without_command(self):
        with tempfile.TemporaryDirectory() as tempdir:
            state = state_with_patch(tempdir, "src/app.py")
            verifier = OutcomeVerifier(
                command=None,
                cwd=tempdir,
                task_constraint_verifier=TaskConstraintVerifier(
                    TaskConstraintSpec(required_changed_paths=["src/app.py"]),
                    workspace_root=tempdir,
                ),
            )

            report = verifier.verify(state, "Done.")

        self.assertEqual(report.status, VerificationStatus.PASSED)
        self.assertEqual(report.summary, "All deterministic task constraints passed.")
        self.assertEqual(report.checks[-2].name, "task_constraints")
        self.assertEqual(report.checks[-2].status, VerificationStatus.PASSED)
        self.assertEqual(report.checks[-1].name, "verification_command")
        self.assertEqual(report.checks[-1].status, VerificationStatus.SKIPPED)

    def test_constraint_failure_overrides_passing_command(self):
        provider = MockProvider([
            ModelResponse.tool_use(
                tool_use_id="toolu_1",
                name="write_file",
                tool_input={"path": "docs/notes.md", "content": "notes\n"},
                text="I will write notes.",
                model="mock-model",
            ),
            ModelResponse.text("Done.", model="mock-model"),
        ])

        with tempfile.TemporaryDirectory() as tempdir:
            config = Config(
                model_provider="mock",
                model="mock-model",
                permission_mode=PermissionMode.AUTO,
                workspace_root=tempdir,
                trajectory_dir=tempdir,
                verification_command=python_command("print('tests pass')"),
                task_forbidden_changed_paths=["docs/*"],
            )
            agent = AgentLoop(config=config, provider=provider)

            with redirect_stdout(StringIO()):
                agent.run("do not change docs")

            state = agent.last_state
            self.assertIsNotNone(state)
            assert state is not None
            events = agent.trajectory_store.read_events(state.task_id)

        event_types = [event["event_type"] for event in events]
        metrics = analyze_state(state)

        self.assertEqual(state.status.value, "failed")
        self.assertEqual(state.verification_report["status"], "failed")
        self.assertEqual(metrics.verification_status, "failed")
        self.assertEqual(metrics.task_constraint_status, "failed")
        self.assertTrue(metrics.task_constraint_failed)
        self.assertEqual(metrics.task_constraint_violation_count, 1)
        self.assertIn("task_constraint_violation", metrics.reflection_categories)
        self.assertIn("reflection_completed", event_types)
        self.assertIn("task_failed", event_types)


if __name__ == "__main__":
    unittest.main()
