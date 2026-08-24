"""Tests for retry strategy matrix decisions."""

from __future__ import annotations

import unittest

from codeagentx.reflection import RetryStrategyMatrix, RetryStrategyName


class TestRetryStrategyMatrix(unittest.TestCase):
    def test_test_failure_prefers_focused_test_fix(self):
        plan = RetryStrategyMatrix().decide(
            {
                "retryable": True,
                "signals": [{
                    "category": "test_failure",
                    "severity": "error",
                    "message": "tests failed",
                    "evidence": {"failure_names": ["tests/test_app.py::test_value"]},
                }],
            },
            ranked_context_report={
                "candidates": [{
                    "path": "app.py",
                    "line": 1,
                    "score": 90,
                    "sources": ["ast"],
                }],
            },
        )

        self.assertEqual(plan.strategy, RetryStrategyName.FOCUSED_TEST_FIX)
        self.assertTrue(plan.should_retry)
        self.assertIn("inspect_ranked_context", plan.actions)
        self.assertIn("rerun_focused_tests", plan.actions)
        self.assertIn("test_failure", plan.categories)

    def test_non_retryable_sandbox_violation_stops(self):
        plan = RetryStrategyMatrix().decide({
            "retryable": False,
            "signals": [{
                "category": "sandbox_violation",
                "severity": "critical",
                "message": "outside workspace",
                "evidence": {"violation": "outside workspace"},
            }],
        })

        self.assertEqual(plan.strategy, RetryStrategyName.STOP_FOR_INTERVENTION)
        self.assertFalse(plan.should_retry)
        self.assertIn("request_intervention", plan.actions)

    def test_patch_policy_violation_reduces_patch_scope(self):
        plan = RetryStrategyMatrix().decide({
            "retryable": True,
            "signals": [{
                "category": "patch_policy_violation",
                "severity": "error",
                "message": "too many lines",
                "evidence": {"total_changed_lines": 2000},
            }],
        })

        self.assertEqual(plan.strategy, RetryStrategyName.PATCH_SCOPE_REDUCTION)
        self.assertTrue(plan.should_retry)
        self.assertIn("inspect_patch_policy", plan.actions)
        self.assertIn("reduce_patch_scope", plan.actions)

    def test_task_constraint_violation_repairs_constraints(self):
        plan = RetryStrategyMatrix().decide({
            "retryable": True,
            "signals": [{
                "category": "task_constraint_violation",
                "severity": "error",
                "message": "task constraints failed",
                "evidence": {"violation_count": 1},
            }],
        })

        self.assertEqual(plan.strategy, RetryStrategyName.TASK_CONSTRAINT_REPAIR)
        self.assertTrue(plan.should_retry)
        self.assertIn("inspect_task_constraints", plan.actions)
        self.assertIn("satisfy_required_constraints", plan.actions)

    def test_no_progress_changes_approach(self):
        plan = RetryStrategyMatrix().decide({
            "retryable": True,
            "signals": [{
                "category": "no_progress",
                "severity": "warning",
                "message": "same tool failed three times",
                "evidence": {"tool_name": "edit_file"},
            }],
        })

        self.assertEqual(plan.strategy, RetryStrategyName.CHANGE_APPROACH)
        self.assertIn("change_approach", plan.actions)
        self.assertIn("avoid_repeated_actions", plan.actions)


if __name__ == "__main__":
    unittest.main()
