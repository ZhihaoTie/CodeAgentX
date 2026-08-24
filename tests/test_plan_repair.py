"""Tests for planner-level repair guidance."""

from __future__ import annotations

import tempfile
import unittest

from codeagentx.agent import AgentLoop, AgentState, PlanStepKind
from codeagentx.agent.planner import build_plan_repair, build_runtime_plan
from codeagentx.config import Config, PermissionMode
from codeagentx.evaluation import analyze_state
from codeagentx.models import MockProvider


class TestPlanRepair(unittest.TestCase):
    def test_builds_focused_test_repair_from_retry_decision(self):
        repair = build_plan_repair(
            {
                "status": "retry",
                "reason": "reflection report is retryable and budget remains",
                "retry_index": 1,
                "strategy": {
                    "strategy": "focused_test_fix",
                    "actions": [
                        "inspect_failing_tests",
                        "rerun_focused_tests",
                        "apply_minimal_fix",
                    ],
                    "categories": ["test_failure"],
                    "prompt_instructions": [
                        "Rerun the narrowest verification command first.",
                    ],
                },
            },
            _test_failure_report(),
            config=Config(verification_command="python -m pytest tests -q"),
        )

        self.assertIsNotNone(repair)
        assert repair is not None
        self.assertEqual(repair.strategy, "focused_test_fix")
        self.assertEqual(repair.target_step_kind, PlanStepKind.VERIFY_OUTCOME.value)
        self.assertEqual(repair.focused_test_targets, [
            "tests/test_math.py::test_add",
            "tests/test_math.py::test_subtract",
        ])
        self.assertIn(
            "python -m pytest tests -q tests/test_math.py::test_add",
            repair.focused_test_command,
        )
        self.assertIn("Runtime", "Runtime plan repair:\n" + repair.prompt_fragment())
        self.assertTrue(any(
            kind == "repair_1_rerun_focused_tests"
            for kind, _description in repair.to_plan_items()
        ))

    def test_retry_scheduler_records_plan_repair_and_prompt(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = Config(
                model_provider="mock",
                model="mock-model",
                permission_mode=PermissionMode.AUTO,
                workspace_root=tempdir,
                trajectory_dir=tempdir,
                verification_command="python -m pytest tests -q",
                enable_context_ranking=False,
                max_reflection_retries=1,
            )
            agent = AgentLoop(config=config, provider=MockProvider())
            state = AgentState(goal="repair failing tests")
            state.set_plan(build_runtime_plan(state.goal, config))

            scheduled = agent._schedule_reflection_retry(state, _test_failure_report())
            events = agent.trajectory_store.read_events(state.task_id)

        metrics = analyze_state(state)
        prompt = agent.context.messages[-1]["content"]
        event_types = [event["event_type"] for event in events]
        repair_step_kinds = [
            step.kind
            for step in (state.plan.steps if state.plan is not None else [])
            if step.kind.startswith("repair_1_")
        ]

        self.assertTrue(scheduled)
        self.assertEqual(len(state.plan_repair_reports), 1)
        self.assertEqual(state.plan_repair_reports[0]["strategy"], "focused_test_fix")
        self.assertEqual(metrics.plan_repair_count, 1)
        self.assertEqual(metrics.plan_repair_last_strategy, "focused_test_fix")
        self.assertIn("tests/test_math.py::test_add", metrics.plan_repair_focused_test_command or "")
        self.assertIn("Runtime plan repair:", prompt)
        self.assertIn("Suggested focused test command:", prompt)
        self.assertIn("plan_repair_created", event_types)
        self.assertIn("repair_1_rerun_focused_tests", repair_step_kinds)

    def test_focused_command_normalizes_unittest_failure_names(self):
        repair = build_plan_repair(
            {
                "status": "retry",
                "reason": "reflection report is retryable and budget remains",
                "retry_index": 1,
                "strategy": {
                    "strategy": "focused_test_fix",
                    "actions": ["rerun_focused_tests"],
                    "categories": ["test_failure"],
                },
            },
            {
                "summary": "Failure reflection generated.",
                "retryable": True,
                "signals": [{
                    "category": "test_failure",
                    "severity": "error",
                    "message": "unittest reported failing tests",
                    "evidence": {
                        "framework": "unittest",
                        "status": "failed",
                        "failure_names": [
                            "test_math (tests.TestMath.test_math)",
                            "test_io (tests.TestMath.test_io)",
                        ],
                    },
                }],
            },
            config=Config(
                verification_command="python -B -m unittest discover -s tests -v",
            ),
        )

        self.assertIsNotNone(repair)
        assert repair is not None
        self.assertEqual(
            repair.focused_test_command,
            "python -m unittest tests.TestMath.test_math tests.TestMath.test_io",
        )

    def test_focused_command_strips_pytest_failure_summary(self):
        repair = build_plan_repair(
            {
                "status": "retry",
                "reason": "reflection report is retryable and budget remains",
                "retry_index": 1,
                "strategy": {
                    "strategy": "focused_test_fix",
                    "actions": ["rerun_focused_tests"],
                    "categories": ["test_failure"],
                },
            },
            {
                "summary": "Failure reflection generated.",
                "retryable": True,
                "signals": [{
                    "category": "test_failure",
                    "severity": "error",
                    "message": "pytest reported failing tests",
                    "evidence": {
                        "framework": "pytest",
                        "status": "failed",
                        "failure_names": [
                            "tests/test_math.py::test_add - AssertionError: 1 != 2",
                        ],
                    },
                }],
            },
            config=Config(verification_command="python -m pytest tests -q"),
        )

        self.assertIsNotNone(repair)
        assert repair is not None
        self.assertEqual(
            repair.focused_test_command,
            "python -m pytest tests -q tests/test_math.py::test_add",
        )


def _test_failure_report() -> dict[str, object]:
    return {
        "summary": "Failure reflection generated.",
        "retryable": True,
        "signals": [{
            "category": "test_failure",
            "severity": "error",
            "message": "pytest reported failing tests",
            "evidence": {
                "framework": "pytest",
                "status": "failed",
                "failure_names": [
                    "tests/test_math.py::test_add",
                    "tests/test_math.py::test_subtract",
                ],
            },
        }],
        "recommendations": [
            "Inspect failing test names and rerun a focused verification command.",
        ],
    }


if __name__ == "__main__":
    unittest.main()
