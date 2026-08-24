"""Tests for single-turn tool execution."""

from __future__ import annotations

import tempfile
import unittest
from io import StringIO
from pathlib import Path

from codeagentx.agent import AgentAction, AgentState, ToolExecutor, TurnRunner
from codeagentx.agent.guidance import ToolGuidanceCheck, ToolGuidanceStatus
from codeagentx.config import Config, PermissionMode
from codeagentx.context import ConversationContext
from codeagentx.tools.base import ToolRegistry
from codeagentx.tools.file_read import FileReadTool
from codeagentx.tools.file_write import FileWriteTool


class TurnRunnerTests(unittest.TestCase):
    def test_executes_tools_records_state_and_appends_tool_results(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "sample.txt"
            path.write_text("hello\n", encoding="utf-8")
            config = Config(workspace_root=tempdir)
            context = ConversationContext(config=config)
            registry = ToolRegistry()
            registry.register(FileReadTool())
            runner = TurnRunner(
                tool_executor=ToolExecutor(registry=registry, config=config),
                context=context,
                output=StringIO(),
            )
            state = AgentState(goal="inspect")

            result = runner.execute_tool_calls(
                [{
                    "id": "toolu_1",
                    "name": "read_file",
                    "input": {"path": "sample.txt"},
                }],
                state,
            )

        self.assertEqual(state.turn_index, 1)
        self.assertEqual(result.failed_tool_calls, 0)
        self.assertIn("hello", result.observations[0].output)
        self.assertEqual(context.messages[-1]["role"], "user")
        self.assertEqual(context.messages[-1]["content"][0]["tool_use_id"], "toolu_1")
        self.assertFalse(context.messages[-1]["content"][0]["is_error"])

    def test_tool_results_use_context_window_policy(self):
        config = Config(
            workspace_root=".",
            max_context_messages=3,
            permission_mode=PermissionMode.AUTO,
        )
        context = ConversationContext(config=config)
        context.add_user_message("initial task")
        context.add_assistant_message([{
            "type": "tool_use",
            "id": "toolu_1",
            "name": "bash",
            "input": {"command": "echo ok"},
        }])
        runner = TurnRunner(
            tool_executor=ToolExecutor(config=config),
            context=context,
            output=StringIO(),
        )

        runner.execute_tool_calls(
            [{
                "id": "toolu_1",
                "name": "bash",
                "input": {"command": "echo ok"},
            }],
            AgentState(goal="verify"),
        )

        self.assertEqual(len(context.messages), 3)
        self.assertEqual(context.messages[1]["role"], "assistant")
        self.assertEqual(context.messages[2]["role"], "user")
        self.assertEqual(context.messages[2]["content"][0]["type"], "tool_result")

    def test_guidance_can_block_write_without_touching_disk(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = Config(
                workspace_root=tempdir,
                permission_mode=PermissionMode.AUTO,
            )
            context = ConversationContext(config=config)
            registry = ToolRegistry()
            registry.register(FileWriteTool())
            blocked_path = Path(tempdir) / "blocked.txt"

            def block_everything(state: AgentState, action: AgentAction):
                return ToolGuidanceCheck(
                    status=ToolGuidanceStatus.BLOCKED,
                    reason="test guidance",
                    strategy="unit-test",
                )

            runner = TurnRunner(
                tool_executor=ToolExecutor(registry=registry, config=config),
                context=context,
                guidance_callback=block_everything,
                output=StringIO(),
            )
            state = AgentState(goal="do not write")

            result = runner.execute_tool_calls(
                [{
                    "id": "toolu_block",
                    "name": "write_file",
                    "input": {"path": "blocked.txt", "content": "nope"},
                }],
                state,
            )

        self.assertFalse(blocked_path.exists())
        self.assertEqual(result.failed_tool_calls, 1)
        self.assertTrue(result.observations[0].is_error)
        self.assertIn("Blocked by retry planning guidance", result.observations[0].output)
        self.assertTrue(context.messages[-1]["content"][0]["is_error"])


if __name__ == "__main__":
    unittest.main()
