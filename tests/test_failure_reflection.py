"""Tests for deterministic failure reflection."""

from __future__ import annotations

import unittest

from codeagentx.agent import AgentAction, AgentObservation, AgentState
from codeagentx.reflection import FailureCategory, FailureReflector


class TestFailureReflector(unittest.TestCase):
    def test_extracts_verification_and_test_failure_signals(self):
        state = AgentState(goal="fix failing tests")
        state.set_verification_report({
            "status": "failed",
            "summary": "verification command failed with code 1",
            "checks": [{
                "name": "verification_command",
                "status": "failed",
                "message": "verification command failed with code 1",
                "metadata": {
                    "command": "python -m unittest",
                    "cwd": ".",
                    "exit_code": 1,
                    "test_result": {
                        "recognized": True,
                        "framework": "unittest",
                        "status": "failed",
                        "total": 3,
                        "passed": 1,
                        "failed": 1,
                        "errors": 1,
                        "skipped": 0,
                        "failure_names": ["test_login", "test_logout"],
                    },
                    "sandbox": {
                        "sandbox_type": "local",
                        "status": "failed",
                    },
                },
            }],
        })
        state.fail("verification failed")

        report = FailureReflector().reflect(state, "Done.")
        categories = _categories(report)

        self.assertIn(FailureCategory.TEST_FAILURE.value, categories)
        self.assertIn(FailureCategory.VERIFICATION_FAILED.value, categories)
        self.assertTrue(report.retryable)
        self.assertIn("focused verification", " ".join(report.recommendations))

    def test_classifies_sandbox_timeout_as_retryable(self):
        state = AgentState(goal="run slow tests")
        state.set_verification_report(_verification_report_with_sandbox(
            sandbox_status="timed_out",
            message="verification command timed out after 1s",
            timed_out=True,
        ))
        state.fail("verification timed out")

        report = FailureReflector().reflect(state, "Done.")

        self.assertIn(FailureCategory.SANDBOX_TIMEOUT.value, _categories(report))
        self.assertTrue(report.retryable)

    def test_classifies_sandbox_violation_as_non_retryable(self):
        state = AgentState(goal="run outside workspace")
        state.set_verification_report(_verification_report_with_sandbox(
            sandbox_status="violation",
            message="cwd outside workspace",
            violation="path escapes workspace",
        ))
        state.fail("sandbox violation")

        report = FailureReflector().reflect(state, "Done.")

        self.assertIn(FailureCategory.SANDBOX_VIOLATION.value, _categories(report))
        self.assertFalse(report.retryable)

    def test_detects_tool_errors_and_no_progress(self):
        state = AgentState(goal="inspect missing file")
        for _index in range(3):
            state.add_step(
                AgentAction(tool_name="read_file", tool_input={"path": "missing.py"}),
                AgentObservation(
                    tool_name="read_file",
                    output="file not found",
                    is_error=True,
                ),
            )
        state.fail("max turns reached")

        report = FailureReflector().reflect(state)
        categories = _categories(report)

        self.assertIn(FailureCategory.TOOL_ERRORS.value, categories)
        self.assertIn(FailureCategory.NO_PROGRESS.value, categories)

    def test_rollback_failure_is_non_retryable(self):
        state = AgentState(goal="rollback broken patch")
        state.set_rollback_report({
            "status": "partial",
            "attempted": 2,
            "restored": 1,
            "failed": 1,
        })
        state.fail("verification failed")

        report = FailureReflector().reflect(state)

        self.assertIn(FailureCategory.ROLLBACK_FAILED.value, _categories(report))
        self.assertFalse(report.retryable)

    def test_patch_policy_critical_violation_is_non_retryable(self):
        state = AgentState(goal="avoid forbidden files")
        state.set_patch_policy_report({
            "status": "failed",
            "summary": "Patch policy failed with 1 violation.",
            "changed_files": 1,
            "patch_count": 1,
            "total_changed_lines": 1,
            "violations": [{
                "rule": "forbidden_path",
                "severity": "critical",
                "message": "Patch modifies forbidden path: .env",
                "evidence": {"path": ".env"},
            }],
        })
        state.fail("patch policy failed")

        report = FailureReflector().reflect(state)

        self.assertIn(FailureCategory.PATCH_POLICY_VIOLATION.value, _categories(report))
        self.assertFalse(report.retryable)

    def test_unknown_signal_when_no_known_evidence_exists(self):
        state = AgentState(goal="unknown failure")
        state.add_step(
            AgentAction(tool_name="glob", tool_input={"pattern": "*.py"}),
            AgentObservation(tool_name="glob", output="app.py"),
        )
        state.fail("custom failure")

        report = FailureReflector().reflect(state)

        self.assertEqual(_categories(report), [FailureCategory.UNKNOWN.value])
        self.assertTrue(report.retryable)


def _verification_report_with_sandbox(
    *,
    sandbox_status: str,
    message: str,
    timed_out: bool = False,
    violation: str = "",
) -> dict[str, object]:
    return {
        "status": "failed",
        "summary": message,
        "checks": [{
            "name": "verification_command",
            "status": "failed",
            "message": message,
            "metadata": {
                "command": "python -m unittest",
                "cwd": ".",
                "exit_code": None,
                "timed_out": timed_out,
                "sandbox": {
                    "sandbox_type": "local",
                    "status": sandbox_status,
                    "timed_out": timed_out,
                    "violation": violation,
                },
            },
        }],
    }


def _categories(report) -> list[str]:
    return [signal.category.value for signal in report.signals]


if __name__ == "__main__":
    unittest.main()
