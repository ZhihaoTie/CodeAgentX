"""Tests for workspace path policy and permission gating."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codeagentx.agent import AgentAction, ToolExecutor
from codeagentx.config import Config, PermissionMode
from codeagentx.permissions import PermissionGate
from codeagentx.security import WorkspacePathPolicy
from codeagentx.tools.base import ToolRegistry
from codeagentx.tools.file_edit import FileEditTool
from codeagentx.tools.file_read import FileReadTool
from codeagentx.tools.file_write import FileWriteTool


class TestWorkspacePathPolicy(unittest.TestCase):
    def test_allows_relative_path_inside_workspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            policy = WorkspacePathPolicy(tmpdir)

            result = policy.check_path("src/app.py")

            self.assertTrue(result.allowed)
            self.assertEqual(result.path, Path(tmpdir).resolve() / "src" / "app.py")

    def test_rejects_parent_traversal_outside_workspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            policy = WorkspacePathPolicy(tmpdir)

            result = policy.check_path("../outside.txt")

            self.assertFalse(result.allowed)
            self.assertIn("outside workspace", result.reason)

    def test_rejects_absolute_path_outside_workspace(self):
        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as outside:
            policy = WorkspacePathPolicy(workspace)

            result = policy.check_path(Path(outside) / "secret.txt")

            self.assertFalse(result.allowed)
            self.assertIn("outside workspace", result.reason)


class TestWorkspaceGuardIntegration(unittest.TestCase):
    def test_executor_blocks_read_outside_workspace(self):
        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as outside:
            outside_file = Path(outside) / "secret.txt"
            outside_file.write_text("secret")
            config = Config(
                permission_mode=PermissionMode.AUTO,
                workspace_root=workspace,
            )
            registry = ToolRegistry()
            registry.register(FileReadTool())
            executor = ToolExecutor(registry=registry, config=config)

            observation = executor.execute(AgentAction(
                tool_name="read_file",
                tool_input={"path": str(outside_file)},
            ))

            self.assertTrue(observation.is_error)
            self.assertIn("outside workspace", observation.output)

    def test_executor_allows_relative_write_inside_workspace(self):
        with tempfile.TemporaryDirectory() as workspace:
            config = Config(
                permission_mode=PermissionMode.AUTO,
                workspace_root=workspace,
            )
            registry = ToolRegistry()
            registry.register(FileWriteTool())
            executor = ToolExecutor(registry=registry, config=config)

            observation = executor.execute(AgentAction(
                tool_name="write_file",
                tool_input={"path": "nested/output.txt", "content": "hello"},
            ))

            output_path = Path(workspace) / "nested" / "output.txt"
            self.assertFalse(observation.is_error)
            self.assertEqual(output_path.read_text(), "hello")

    def test_executor_blocks_edit_outside_workspace(self):
        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as outside:
            outside_file = Path(outside) / "app.py"
            outside_file.write_text("old")
            config = Config(
                permission_mode=PermissionMode.AUTO,
                workspace_root=workspace,
            )
            registry = ToolRegistry()
            registry.register(FileEditTool())
            executor = ToolExecutor(registry=registry, config=config)

            observation = executor.execute(AgentAction(
                tool_name="edit_file",
                tool_input={
                    "path": str(outside_file),
                    "old_string": "old",
                    "new_string": "new",
                },
            ))

            self.assertTrue(observation.is_error)
            self.assertIn("outside workspace", observation.output)
            self.assertEqual(outside_file.read_text(), "old")


class TestPermissionGateWriteAsks(unittest.TestCase):
    def test_ask_mode_prompts_for_write_file(self):
        with tempfile.TemporaryDirectory() as workspace:
            gate = PermissionGate(Config(
                permission_mode=PermissionMode.ASK,
                workspace_root=workspace,
            ))

            with patch("builtins.input", return_value="n") as mocked_input:
                result = gate.check(FileWriteTool(), {"path": "out.txt", "content": "hello"})

            self.assertIsNotNone(result)
            assert result is not None
            self.assertTrue(result.is_error)
            self.assertIn("user rejected", result.output)
            mocked_input.assert_called_once()

    def test_ask_mode_prompts_for_edit_file(self):
        with tempfile.TemporaryDirectory() as workspace:
            gate = PermissionGate(Config(
                permission_mode=PermissionMode.ASK,
                workspace_root=workspace,
            ))

            with patch("builtins.input", return_value="y") as mocked_input:
                result = gate.check(FileEditTool(), {
                    "path": "app.py",
                    "old_string": "old",
                    "new_string": "new",
                })

            self.assertIsNone(result)
            mocked_input.assert_called_once()


if __name__ == "__main__":
    unittest.main()
