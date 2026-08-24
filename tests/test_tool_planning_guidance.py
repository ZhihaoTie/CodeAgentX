"""Tests for strategy-guided runtime tool planning."""

from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from codeagentx.agent import AgentAction, AgentLoop, AgentState, ToolExecutor
from codeagentx.agent.guidance import ToolGuidanceStatus, ToolPlanningGuidance
from codeagentx.config import Config, PermissionMode
from codeagentx.context import ConversationContext
from codeagentx.evaluation import analyze_state
from codeagentx.models import MockProvider


class TestToolPlanningGuidance(unittest.TestCase):
    def test_task_constraint_strategy_blocks_forbidden_write_paths(self):
        guidance = ToolPlanningGuidance.from_retry_decision(
            {
                "status": "retry",
                "retry_index": 1,
                "strategy": {
                    "strategy": "task_constraint_repair",
                    "actions": ["inspect_task_constraints", "avoid_forbidden_changes"],
                    "categories": ["task_constraint_violation"],
                },
            },
            {
                "signals": [{
                    "category": "task_constraint_violation",
                    "evidence": {
                        "violations": [
                            {
                                "type": "forbidden_changed_path_modified",
                                "pattern": "docs/*",
                                "matches": ["docs/notes.md"],
                            },
                            {
                                "type": "required_changed_path_missing",
                                "pattern": "src/*.py",
                            },
                        ],
                    },
                }],
            },
            config=Config(
                task_forbidden_changed_paths=["secrets/*"],
                task_required_changed_paths=["src/*.py"],
            ),
        )

        self.assertIsNotNone(guidance)
        assert guidance is not None
        self.assertEqual(guidance.strategy, "task_constraint_repair")
        self.assertIn("docs/*", guidance.blocked_write_patterns)
        self.assertIn("secrets/*", guidance.blocked_write_patterns)
        self.assertEqual(guidance.required_changed_patterns, ["src/*.py"])

        blocked = guidance.evaluate(
            AgentAction(
                tool_name="write_file",
                tool_input={"path": "docs/notes.md", "content": "unsafe"},
            )
        )
        aligned = guidance.evaluate(
            AgentAction(
                tool_name="write_file",
                tool_input={"path": "src/app.py", "content": "safe"},
            )
        )
        warning = guidance.evaluate(
            AgentAction(tool_name="unknown_tool", tool_input={})
        )

        self.assertEqual(blocked.status, ToolGuidanceStatus.BLOCKED)
        self.assertIn("docs/*", blocked.reason)
        self.assertEqual(aligned.status, ToolGuidanceStatus.ALIGNED)
        self.assertEqual(warning.status, ToolGuidanceStatus.WARNING)

    def test_loop_records_blocked_guidance_observation_without_writing_file(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = Config(
                workspace_root=tempdir,
                permission_mode=PermissionMode.AUTO,
                trajectory_dir=None,
            )
            guidance = ToolPlanningGuidance(
                strategy="task_constraint_repair",
                retry_index=1,
                preferred_tools=["read_file", "write_file", "edit_file"],
                blocked_write_patterns=["docs/*"],
                workspace_root=tempdir,
            )
            loop = AgentLoop.__new__(AgentLoop)
            loop.context = ConversationContext(config=config)
            loop.tool_executor = ToolExecutor(config=config)
            loop.active_tool_guidance = guidance
            loop.trajectory_store = None
            state = AgentState(goal="avoid docs")

            with redirect_stdout(StringIO()):
                loop._execute_tool_calls(
                    [{
                        "id": "toolu_block",
                        "name": "write_file",
                        "input": {"path": "docs/blocked.md", "content": "blocked"},
                    }],
                    state,
                )

            blocked_path = Path(tempdir) / "docs" / "blocked.md"
            metrics = analyze_state(state)

        observation = state.trajectory[0].observation
        tool_result = loop.context.messages[-1]["content"][0]

        self.assertFalse(blocked_path.exists())
        self.assertTrue(observation.is_error)
        self.assertIn("Blocked by retry planning guidance", observation.output)
        self.assertEqual(
            observation.metadata["tool_planning_guidance"]["status"],
            "blocked",
        )
        self.assertTrue(tool_result["is_error"])
        self.assertEqual(metrics.tool_planning_guidance_blocked, 1)
        self.assertEqual(metrics.failed_tool_calls, 1)

    def test_retry_scheduler_attaches_runtime_guidance_to_state_and_prompt(self):
        reflection_report = {
            "summary": "Failure reflection generated.",
            "retryable": True,
            "signals": [{
                "category": "task_constraint_violation",
                "severity": "error",
                "message": "task constraints failed",
                "evidence": {
                    "violation_count": 1,
                    "violations": [{
                        "type": "forbidden_changed_path_modified",
                        "pattern": "docs/*",
                        "matches": ["docs/notes.md"],
                    }],
                },
            }],
        }

        with tempfile.TemporaryDirectory() as tempdir:
            agent = AgentLoop(
                config=Config(
                    model_provider="mock",
                    model="mock-model",
                    workspace_root=tempdir,
                    trajectory_dir=None,
                    permission_mode=PermissionMode.AUTO,
                    enable_context_ranking=False,
                    max_reflection_retries=1,
                    task_forbidden_changed_paths=["docs/*"],
                ),
                provider=MockProvider(),
            )
            state = AgentState(goal="repair constraints")

            scheduled = agent._schedule_reflection_retry(state, reflection_report)

        self.assertTrue(scheduled)
        self.assertIsNotNone(agent.active_tool_guidance)
        self.assertEqual(len(state.tool_planning_guidance_reports), 1)
        self.assertEqual(
            state.tool_planning_guidance_reports[0]["strategy"],
            "task_constraint_repair",
        )
        self.assertIn(
            "Runtime tool planning guidance:",
            agent.context.messages[-1]["content"],
        )
        self.assertIn("docs/*", agent.context.messages[-1]["content"])


if __name__ == "__main__":
    unittest.main()
