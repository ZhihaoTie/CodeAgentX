"""Tests for bash command risk classification."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codeagentx.agent import AgentAction, ToolExecutor
from codeagentx.config import Config, PermissionMode
from codeagentx.permissions import PermissionGate
from codeagentx.security import CommandRisk, CommandRiskClassifier
from codeagentx.tools.bash_tool import BashTool
from codeagentx.tools.base import ToolRegistry


class TestCommandRiskClassifier(unittest.TestCase):
    def setUp(self):
        self.classifier = CommandRiskClassifier(
            allowed_prefixes=["echo", "git status", "python"],
            denied_patterns=["rm -rf /", "git reset --hard"],
        )

    def test_classifies_safe_command(self):
        result = self.classifier.classify("echo hello")

        self.assertEqual(result.risk, CommandRisk.SAFE)
        self.assertEqual(result.matched_pattern, "echo")

    def test_classifies_write_command(self):
        result = self.classifier.classify("echo hello > out.txt")

        self.assertEqual(result.risk, CommandRisk.WRITE)
        self.assertEqual(result.matched_pattern, ">")

    def test_classifies_network_command_before_safe_prefix(self):
        result = self.classifier.classify("python -m pip install pytest")

        self.assertEqual(result.risk, CommandRisk.NETWORK)
        self.assertIn("network", result.reason)

    def test_classifies_dangerous_command_first(self):
        result = self.classifier.classify("git reset --hard HEAD")

        self.assertEqual(result.risk, CommandRisk.DANGEROUS)
        self.assertEqual(result.matched_pattern, "git reset --hard")

    def test_classifies_unknown_command(self):
        result = self.classifier.classify("custom-build-command --fast")

        self.assertEqual(result.risk, CommandRisk.UNKNOWN)


class TestBashRiskPermissionIntegration(unittest.TestCase):
    def test_auto_mode_denies_dangerous_bash(self):
        gate = PermissionGate(Config(permission_mode=PermissionMode.AUTO))

        result = gate.check(BashTool(), {"command": "git reset --hard HEAD"})

        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result.is_error)
        self.assertIn("Permission denied", result.output)

    def test_ask_mode_allows_safe_bash_without_prompt(self):
        gate = PermissionGate(Config(permission_mode=PermissionMode.ASK))

        with patch("builtins.input") as mocked_input:
            result = gate.check(BashTool(), {"command": "echo hello"})

        self.assertIsNone(result)
        mocked_input.assert_not_called()

    def test_ask_mode_prompts_for_network_bash(self):
        gate = PermissionGate(Config(permission_mode=PermissionMode.ASK))

        with patch("builtins.input", return_value="n") as mocked_input:
            result = gate.check(BashTool(), {"command": "curl https://example.com"})

        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result.is_error)
        self.assertIn("user rejected", result.output)
        mocked_input.assert_called_once()

    def test_ask_mode_prompts_for_unknown_bash(self):
        gate = PermissionGate(Config(permission_mode=PermissionMode.ASK))

        with patch("builtins.input", return_value="n") as mocked_input:
            result = gate.check(BashTool(), {"command": "custom-build-command"})

        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result.is_error)
        mocked_input.assert_called_once()


class TestBashRiskMetadata(unittest.TestCase):
    def test_executor_records_safe_command_risk_metadata(self):
        with tempfile.TemporaryDirectory() as workspace:
            registry = ToolRegistry()
            registry.register(BashTool())
            executor = ToolExecutor(
                registry=registry,
                config=Config(permission_mode=PermissionMode.AUTO, workspace_root=workspace),
            )

            observation = executor.execute(AgentAction(
                tool_name="bash",
                tool_input={"command": "echo hello"},
            ))

        self.assertFalse(observation.is_error)
        self.assertEqual(
            observation.metadata["permission"]["command"]["risk"],
            "safe",
        )
        self.assertEqual(
            Path(observation.metadata["permission"]["workspace_path"]["normalized_path"]).resolve(),
            Path(workspace).resolve(),
        )

    def test_bash_default_cwd_uses_relative_workspace_root_once(self):
        with tempfile.TemporaryDirectory() as tempdir:
            workspace = Path(tempdir) / "workspace"
            workspace.mkdir()
            previous = Path.cwd()
            try:
                import os

                os.chdir(tempdir)
                registry = ToolRegistry()
                registry.register(BashTool())
                executor = ToolExecutor(
                    registry=registry,
                    config=Config(
                        permission_mode=PermissionMode.AUTO,
                        workspace_root="workspace",
                    ),
                )

                observation = executor.execute(AgentAction(
                    tool_name="bash",
                    tool_input={"command": "echo hello"},
                ))
            finally:
                os.chdir(previous)

        self.assertFalse(observation.is_error)
        self.assertEqual(
            Path(observation.metadata["permission"]["workspace_path"]["normalized_path"]).resolve(),
            workspace.resolve(),
        )

    def test_executor_records_dangerous_command_risk_metadata(self):
        registry = ToolRegistry()
        registry.register(BashTool())
        executor = ToolExecutor(
            registry=registry,
            config=Config(permission_mode=PermissionMode.AUTO),
        )

        observation = executor.execute(AgentAction(
            tool_name="bash",
            tool_input={"command": "rm -rf /"},
        ))

        self.assertTrue(observation.is_error)
        self.assertEqual(
            observation.metadata["permission"]["command"]["risk"],
            "dangerous",
        )


if __name__ == "__main__":
    unittest.main()
