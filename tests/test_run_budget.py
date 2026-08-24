"""Tests for run-level resource accounting."""

from __future__ import annotations

import time
import unittest

from codeagentx.agent import RunBudget


class RunBudgetTests(unittest.TestCase):
    def test_tracks_turns_tool_calls_and_provider_usage(self):
        budget = RunBudget(max_turns=3, max_tool_calls=4)

        self.assertIsNone(budget.begin_turn())
        budget.record_model_usage({
            "input_tokens": 7,
            "output_tokens": 11,
        })
        budget.record_tool_calls(2)

        report = budget.to_dict()

        self.assertEqual(report["turns"], 1)
        self.assertEqual(report["tool_calls"], 2)
        self.assertEqual(report["input_tokens"], 7)
        self.assertEqual(report["output_tokens"], 11)
        self.assertEqual(report["total_tokens"], 18)
        self.assertIsNone(budget.limit_reason())

    def test_tool_call_limit_is_reported(self):
        budget = RunBudget(max_turns=3, max_tool_calls=1)
        budget.record_tool_calls(1)

        self.assertEqual(
            budget.limit_reason(),
            "max tool calls reached (1)",
        )

    def test_records_exhaustion_reason_in_final_report(self):
        budget = RunBudget(max_turns=3, max_tool_calls=1)
        budget.mark_exhausted("max tool calls reached (1)")

        report = budget.to_dict()

        self.assertTrue(report["exhausted"])
        self.assertEqual(
            report["exhausted_reason"],
            "max tool calls reached (1)",
        )

    def test_elapsed_limit_is_reported(self):
        budget = RunBudget(
            max_turns=3,
            max_run_seconds=0.001,
            started_at=time.monotonic() - 1,
        )

        self.assertEqual(
            budget.limit_reason(),
            "max run time reached (0.001s)",
        )


if __name__ == "__main__":
    unittest.main()
