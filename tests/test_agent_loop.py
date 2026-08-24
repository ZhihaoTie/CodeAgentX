"""Tests for permissions, context management, and system prompt building.

Note: The full AgentLoop requires an Anthropic API key, so we test the
surrounding components that don't need network access.
"""

from __future__ import annotations

import unittest

from codeagentx.config import Config, PermissionMode
from codeagentx.context import ContextWindow, ConversationContext
from codeagentx.permissions import PermissionGate
from codeagentx.system_prompt import build_system_prompt
from codeagentx.tools.base import ToolRegistry, ToolResult
from codeagentx.tools.bash_tool import BashTool


class TestPermissionGate(unittest.TestCase):
    def test_auto_mode_allows_all(self):
        config = Config(permission_mode=PermissionMode.AUTO)
        gate = PermissionGate(config)
        tool = BashTool()
        result = gate.check(tool, {"command": "echo hello"})
        self.assertIsNone(result)

    def test_plan_mode_blocks_writes(self):
        config = Config(permission_mode=PermissionMode.PLAN)
        gate = PermissionGate(config)
        tool = BashTool()
        result = gate.check(tool, {"command": "echo hello"})
        self.assertIsNotNone(result)
        self.assertTrue(result.is_error)

    def test_tool_level_denial_takes_priority(self):
        config = Config(permission_mode=PermissionMode.AUTO)
        gate = PermissionGate(config)
        tool = BashTool()
        result = gate.check(tool, {"command": "rm -rf /"})
        self.assertIsNotNone(result)
        self.assertTrue(result.is_error)


class TestConversationContext(unittest.TestCase):
    def test_add_messages(self):
        config = Config(max_context_messages=10)
        ctx = ConversationContext(config=config)
        ctx.add_user_message("hello")
        ctx.add_assistant_message("hi")
        msgs = ctx.get_api_messages()
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["role"], "user")
        self.assertEqual(msgs[1]["role"], "assistant")

    def test_truncation(self):
        config = Config(max_context_messages=5)
        ctx = ConversationContext(config=config)
        for i in range(10):
            ctx.add_user_message(f"msg {i}")
        msgs = ctx.get_api_messages()
        self.assertLessEqual(len(msgs), 5)
        # First message should be preserved
        self.assertEqual(msgs[0]["content"], "msg 0")

    def test_truncation_preserves_tool_exchange(self):
        config = Config(max_context_messages=4)
        ctx = ConversationContext(config=config)
        ctx.add_user_message("initial task")
        ctx.add_user_message("old context")
        ctx.add_assistant_message([{
            "type": "tool_use",
            "id": "toolu_1",
            "name": "read_file",
            "input": {"path": "app.py"},
        }])
        ctx.add_tool_results([{
            "type": "tool_result",
            "tool_use_id": "toolu_1",
            "content": "source",
            "is_error": False,
        }])
        ctx.add_user_message("continue")

        messages = ctx.get_api_messages()

        self.assertLessEqual(len(messages), 4)
        self.assertEqual(messages[0]["content"], "initial task")
        tool_use_index = next(
            index
            for index, message in enumerate(messages)
            if message.get("role") == "assistant"
        )
        self.assertEqual(messages[tool_use_index + 1]["role"], "user")
        self.assertEqual(
            messages[tool_use_index + 1]["content"][0]["type"],
            "tool_result",
        )

    def test_context_window_keeps_tiny_tool_exchange_atomic(self):
        messages = [
            {"role": "user", "content": "task"},
            {
                "role": "assistant",
                "content": [{
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "read_file",
                    "input": {},
                }],
            },
            {
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": "toolu_1",
                    "content": "ok",
                }],
            },
        ]

        trimmed = ContextWindow(max_messages=2).trim(messages)

        self.assertEqual(len(trimmed), 3)
        self.assertEqual(trimmed[1]["role"], "assistant")
        self.assertEqual(trimmed[2]["content"][0]["type"], "tool_result")

    def test_tiny_window_prefers_latest_tool_exchange_over_old_context(self):
        messages = [
            {"role": "user", "content": "task"},
            {"role": "user", "content": "old context"},
            {
                "role": "assistant",
                "content": [{
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "read_file",
                    "input": {},
                }],
            },
            {
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": "toolu_1",
                    "content": "latest",
                }],
            },
        ]

        trimmed = ContextWindow(max_messages=2).trim(messages)

        self.assertEqual(trimmed[0]["content"], "task")
        self.assertEqual(trimmed[1]["role"], "assistant")
        self.assertEqual(trimmed[2]["content"][0]["content"], "latest")

    def test_system_prompt(self):
        ctx = ConversationContext(config=Config())
        ctx.set_system_prompt("You are helpful.")
        self.assertEqual(ctx.system_prompt, "You are helpful.")


class TestSystemPrompt(unittest.TestCase):
    def test_build_includes_tools(self):
        registry = ToolRegistry.default()
        prompt = build_system_prompt(registry, permission_mode="ask")
        self.assertIn("bash", prompt)
        self.assertIn("read_file", prompt)
        self.assertIn("ASK", prompt)

    def test_plan_mode_description(self):
        registry = ToolRegistry.default()
        prompt = build_system_prompt(registry, permission_mode="plan")
        self.assertIn("read-only", prompt)

    def test_build_includes_runtime_context(self):
        registry = ToolRegistry.default()
        prompt = build_system_prompt(
            registry,
            permission_mode="auto",
            workspace_root="D:\\workspace",
            verification_command="python -m unittest discover -s tests -v",
        )

        self.assertIn("Runtime Context", prompt)
        self.assertIn("Workspace root: `D:\\workspace`", prompt)
        self.assertIn("Bash commands already run from the workspace root", prompt)
        self.assertIn("Configured verification command", prompt)
        self.assertIn("python -m unittest discover -s tests -v", prompt)


class TestToolResultDataclass(unittest.TestCase):
    def test_default_not_error(self):
        r = ToolResult(output="ok")
        self.assertFalse(r.is_error)

    def test_error_flag(self):
        r = ToolResult(output="fail", is_error=True)
        self.assertTrue(r.is_error)


if __name__ == "__main__":
    unittest.main()
