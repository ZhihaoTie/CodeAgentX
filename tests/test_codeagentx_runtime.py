"""Tests for the CodeAgent-X runtime layer."""

from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from codeagentx.agent import AgentAction, AgentLoop, AgentState, PlanStepStatus, TaskPlan, ToolExecutor
from codeagentx.context import ConversationContext
from codeagentx.evaluation import analyze_state
from codeagentx.config import Config, PermissionMode
from codeagentx.tools.base import ToolRegistry
from codeagentx.tools.file_read import FileReadTool


class TestTaskPlan(unittest.TestCase):
    def test_plan_progress(self):
        plan = TaskPlan.from_steps("fix login bug", ["find auth", "edit code", "run tests"])

        self.assertEqual(plan.progress(), 0.0)
        self.assertEqual(plan.next_pending().description, "find auth")

        first = plan.next_pending()
        first.mark_started()
        self.assertEqual(first.status, PlanStepStatus.IN_PROGRESS)
        first.mark_done("auth/login.py")

        self.assertAlmostEqual(plan.progress(), 1 / 3)
        self.assertFalse(plan.is_complete())


class TestAgentState(unittest.TestCase):
    def test_records_trajectory_steps(self):
        state = AgentState(goal="inspect repo")
        action = AgentAction(tool_name="read_file", tool_input={"path": "README.md"})
        observation = ToolExecutor().execute(action)

        step = state.add_step(action, observation)

        self.assertEqual(step.turn, 1)
        self.assertEqual(state.turn_index, 1)
        self.assertEqual(state.latest_observation, observation)
        self.assertEqual(state.tool_call_count("read_file"), 1)

    def test_state_finish_and_fail(self):
        state = AgentState(goal="demo")
        state.finish()
        self.assertEqual(state.status.value, "succeeded")

        state.fail("tests failed")
        self.assertEqual(state.status.value, "failed")
        self.assertEqual(state.failure_reason, "tests failed")


class TestToolExecutor(unittest.TestCase):
    def test_execute_known_tool(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.txt"
            path.write_text("hello\n")
            registry = ToolRegistry()
            registry.register(FileReadTool())
            executor = ToolExecutor(
                registry=registry,
                config=Config(workspace_root=tmpdir),
            )
            action = AgentAction(tool_name="read_file", tool_input={"path": str(path)})
            observation = executor.execute(action)

        self.assertFalse(observation.is_error)
        self.assertIn("hello", observation.output)
        self.assertIn("duration_ms", observation.metadata)

    def test_unknown_tool_is_error(self):
        executor = ToolExecutor(registry=ToolRegistry())
        observation = executor.execute(AgentAction(tool_name="missing", tool_input={}))

        self.assertTrue(observation.is_error)
        self.assertIn("unknown tool", observation.output)

    def test_plan_mode_blocks_write_actions(self):
        config = Config(permission_mode=PermissionMode.PLAN)
        executor = ToolExecutor(config=config)
        action = AgentAction(tool_name="bash", tool_input={"command": "echo hello"})

        observation = executor.execute(action)

        self.assertTrue(observation.is_error)
        self.assertIn("blocked in plan", observation.output)

    def test_execute_and_record(self):
        state = AgentState(goal="inspect repo")
        executor = ToolExecutor()
        action = AgentAction(tool_name="glob", tool_input={"pattern": "*.py", "directory": "tests"})

        observation = executor.execute_and_record(state, action)

        self.assertFalse(observation.is_error)
        self.assertEqual(state.turn_index, 1)
        self.assertIn("test_tools.py", observation.output)


class TestAgentLoopTrajectoryIntegration(unittest.TestCase):
    def test_tool_calls_are_recorded_in_agent_state(self):
        config = Config()
        state = AgentState(goal="inspect tests")
        loop = AgentLoop.__new__(AgentLoop)
        loop.context = ConversationContext(config=config)
        loop.tool_executor = ToolExecutor(config=config)

        with redirect_stdout(StringIO()):
            loop._execute_tool_calls(
                [{
                    "id": "toolu_1",
                    "name": "glob",
                    "input": {"pattern": "*.py", "directory": "tests"},
                }],
                state,
            )

        self.assertEqual(state.turn_index, 1)
        self.assertEqual(state.trajectory[0].action.tool_name, "glob")
        self.assertFalse(state.trajectory[0].observation.is_error)
        self.assertEqual(loop.context.messages[-1]["content"][0]["tool_use_id"], "toolu_1")


class TestTrajectoryMetrics(unittest.TestCase):
    def test_analyze_state(self):
        state = AgentState(goal="fix bug")
        state.add_step(
            AgentAction(tool_name="read_file", tool_input={"path": "app.py"}),
            ToolExecutor().execute(AgentAction(tool_name="glob", tool_input={"pattern": "*.py"})),
        )
        state.add_step(
            AgentAction(tool_name="edit_file", tool_input={"path": "app.py"}),
            ToolExecutor().execute(AgentAction(tool_name="missing", tool_input={})),
        )
        state.add_step(
            AgentAction(tool_name="bash", tool_input={"command": "python -m unittest"}),
            ToolExecutor().execute(AgentAction(tool_name="missing", tool_input={})),
        )
        state.add_step(
            AgentAction(tool_name="ast_context", tool_input={"query": "AgentLoop"}),
            ToolExecutor().execute(AgentAction(tool_name="missing", tool_input={})),
        )
        state.finish()

        metrics = analyze_state(state)

        self.assertTrue(metrics.success)
        self.assertEqual(metrics.turns, 4)
        self.assertEqual(metrics.edit_count, 1)
        self.assertEqual(metrics.read_count, 2)
        self.assertEqual(metrics.ast_context_queries, 1)
        self.assertEqual(metrics.test_runs, 1)
        self.assertEqual(metrics.failed_tool_calls, 3)
        self.assertAlmostEqual(metrics.tool_error_rate, 3 / 4)

    def test_analyze_state_includes_run_budget(self):
        state = AgentState(goal="budgeted run")
        state.set_run_budget_report({
            "max_turns": 4,
            "max_tool_calls": 7,
            "max_run_seconds": 12.5,
            "turns": 2,
            "tool_calls": 5,
            "input_tokens": 101,
            "output_tokens": 33,
            "total_tokens": 134,
            "elapsed_seconds": 1.25,
            "exhausted": True,
            "exhausted_reason": "max tool calls reached (7)",
        })

        metrics = analyze_state(state)

        self.assertEqual(metrics.budget_max_turns, 4)
        self.assertEqual(metrics.budget_max_tool_calls, 7)
        self.assertEqual(metrics.budget_max_run_seconds, 12.5)
        self.assertEqual(metrics.budget_turns, 2)
        self.assertEqual(metrics.budget_tool_calls, 5)
        self.assertEqual(metrics.budget_total_tokens, 134)
        self.assertEqual(metrics.budget_elapsed_seconds, 1.25)
        self.assertTrue(metrics.budget_exhausted)
        self.assertEqual(
            metrics.budget_exhausted_reason,
            "max tool calls reached (7)",
        )


if __name__ == "__main__":
    unittest.main()
