"""Tests for patch policy quality gates."""

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
from codeagentx.patching import PatchPolicy, PatchPolicyStatus, PatchTransaction


def python_command(code: str) -> str:
    return f'"{sys.executable}" -c "{code}"'


class TestPatchPolicy(unittest.TestCase):
    def test_passes_small_patch(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "app.py"
            result = PatchTransaction.for_write(path, "value = 1\n").apply(
                backup_root=Path(tempdir) / "backups"
            )

            report = PatchPolicy(forbidden_paths=[]).evaluate([result.to_dict()])

        self.assertEqual(report.status, PatchPolicyStatus.PASSED)
        self.assertEqual(report.changed_files, 1)
        self.assertEqual(report.patch_count, 1)
        self.assertGreater(report.added_lines, 0)

    def test_forbidden_path_fails_as_critical(self):
        patch = _patch(path=".env", diff="+TOKEN=secret\n", bytes_after=13)

        report = PatchPolicy(forbidden_paths=[".env"]).evaluate([patch])

        self.assertEqual(report.status, PatchPolicyStatus.FAILED)
        self.assertEqual(report.violations[0].rule, "forbidden_path")
        self.assertEqual(report.violations[0].severity.value, "critical")

    def test_empty_patch_fails_when_enabled(self):
        patch = _patch(path="app.py", diff="", bytes_before=10, bytes_after=10)

        report = PatchPolicy(forbidden_paths=[]).evaluate([patch])

        self.assertEqual(report.status, PatchPolicyStatus.FAILED)
        self.assertEqual(report.violations[0].rule, "empty_patch")

    def test_changed_file_and_line_limits_fail(self):
        patches = [
            _patch(path="a.py", diff="+one\n+two\n", bytes_after=8),
            _patch(path="b.py", diff="+three\n", bytes_after=6),
        ]

        report = PatchPolicy(
            forbidden_paths=[],
            max_changed_files=1,
            max_total_changed_lines=2,
        ).evaluate(patches)
        rules = {violation.rule for violation in report.violations}

        self.assertEqual(report.status, PatchPolicyStatus.FAILED)
        self.assertIn("changed_file_limit", rules)
        self.assertIn("changed_line_limit", rules)

    def test_diff_truncation_is_warning(self):
        patch = _patch(path="app.py", diff="+value = 1\n", bytes_after=10)
        patch["diff_truncated"] = True

        report = PatchPolicy(forbidden_paths=[]).evaluate([patch])

        self.assertEqual(report.status, PatchPolicyStatus.WARNING)
        self.assertEqual(report.violations[0].rule, "diff_truncated")


class TestAgentLoopPatchPolicy(unittest.TestCase):
    def test_patch_policy_failure_overrides_passing_verification(self):
        provider = MockProvider([
            ModelResponse.tool_use(
                tool_use_id="toolu_1",
                name="write_file",
                tool_input={"path": ".env", "content": "TOKEN=secret\n"},
                text="I will write the config.",
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
            )
            agent = AgentLoop(config=config, provider=provider)

            with redirect_stdout(StringIO()):
                agent.run("write forbidden env file")

            state = agent.last_state
            self.assertIsNotNone(state)
            assert state is not None
            events = agent.trajectory_store.read_events(state.task_id)
            snapshot = agent.trajectory_store.load_state(state.task_id)

        event_types = [event["event_type"] for event in events]
        metrics = analyze_state(state)

        self.assertEqual(state.status.value, "failed")
        self.assertEqual(state.verification_report["status"], "passed")
        self.assertEqual(state.patch_policy_report["status"], "failed")
        self.assertEqual(snapshot["state"]["patch_policy_report"]["status"], "failed")
        self.assertTrue(metrics.verified_success)
        self.assertFalse(metrics.success)
        self.assertTrue(metrics.patch_policy_failed)
        self.assertEqual(metrics.patch_policy_status, "failed")
        self.assertIn("patch_policy_completed", event_types)
        self.assertIn("patch_policy_violation", metrics.reflection_categories)

    def test_patch_policy_can_be_disabled(self):
        provider = MockProvider([
            ModelResponse.tool_use(
                tool_use_id="toolu_1",
                name="write_file",
                tool_input={"path": ".env", "content": "TOKEN=secret\n"},
                text="I will write the config.",
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
                enable_patch_policy=False,
            )
            agent = AgentLoop(config=config, provider=provider)

            with redirect_stdout(StringIO()):
                agent.run("write env file with policy disabled")

            state = agent.last_state
            self.assertIsNotNone(state)
            assert state is not None
            events = agent.trajectory_store.read_events(state.task_id)

        event_types = [event["event_type"] for event in events]

        self.assertEqual(state.status.value, "succeeded")
        self.assertIsNone(state.patch_policy_report)
        self.assertNotIn("patch_policy_completed", event_types)


def _patch(
    *,
    path: str,
    diff: str,
    bytes_before: int = 0,
    bytes_after: int = 0,
) -> dict[str, object]:
    return {
        "transaction_id": "tx-1",
        "operation": "write_file",
        "path": path,
        "before_exists": bytes_before > 0,
        "backup_path": "",
        "diff": diff,
        "diff_truncated": False,
        "bytes_before": bytes_before,
        "bytes_after": bytes_after,
        "applied_at": "2026-07-28T00:00:00+00:00",
    }


if __name__ == "__main__":
    unittest.main()
