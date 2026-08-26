"""Tests for the lightweight local `codeagentx run` entrypoint."""

from __future__ import annotations

import io
from types import SimpleNamespace
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from codeagentx import cli


class CliRunCommandTest(unittest.TestCase):
    def test_run_subcommand_executes_one_shot_prompt(self) -> None:
        with patch("codeagentx.cli.AgentLoop") as agent_loop:
            agent = agent_loop.return_value
            agent.last_state = None
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = cli.main([
                    "run",
                    "--provider",
                    "mock",
                    "--model",
                    "mock-model",
                    "--no-trajectory",
                    "Fix",
                    "the",
                    "tests",
                ])

        self.assertEqual(exit_code, 0)
        agent.run.assert_called_once_with("Fix the tests")
        self.assertIn("CodeAgent-X run: Fix the tests", output.getvalue())
        self.assertIn("CodeAgent-X summary", output.getvalue())

    def test_run_subcommand_requires_prompt(self) -> None:
        stderr = io.StringIO()

        with redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
            cli.main(["run", "--provider", "mock"])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn('the "run" command requires a prompt', stderr.getvalue())

    def test_run_subcommand_defaults_workspace_to_current_directory(self) -> None:
        with patch("codeagentx.cli.AgentLoop") as agent_loop:
            agent = agent_loop.return_value
            agent.last_state = None

            with redirect_stdout(io.StringIO()):
                exit_code = cli.main([
                    "run",
                    "--provider",
                    "mock",
                    "--model",
                    "mock-model",
                    "--no-trajectory",
                    "Fix",
                    "tests",
                ])

        self.assertEqual(exit_code, 0)
        config = agent_loop.call_args.kwargs["config"]
        self.assertEqual(config.workspace_root, ".")

    def test_run_subcommand_can_create_branch_and_commit(self) -> None:
        git_calls: list[list[str]] = []

        def git_checked(command, *, cwd):
            git_calls.append(list(command))
            return ""

        with (
            patch("codeagentx.cli.AgentLoop") as agent_loop,
            patch("codeagentx.cli._git_checked", side_effect=git_checked),
            patch("codeagentx.cli._git_command") as git_command,
        ):
            git_command.side_effect = [" M app.py", " M app.py", " app.py | 2 +-"]
            agent = agent_loop.return_value
            agent.last_state = SimpleNamespace(
                task_id="task-1",
                verification_report={"status": "passed", "summary": "ok"},
            )
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = cli.main([
                    "run",
                    "--provider",
                    "mock",
                    "--model",
                    "mock-model",
                    "--no-trajectory",
                    "--branch",
                    "codeagentx/test",
                    "--commit",
                    "--commit-message",
                    "Fix app",
                    "Fix",
                    "app",
                ])

        self.assertEqual(exit_code, 0)
        self.assertEqual(git_calls[0], ["git", "checkout", "-b", "codeagentx/test"])
        self.assertIn(["git", "add", "-A"], git_calls)
        self.assertIn(["git", "commit", "-m", "Fix app"], git_calls)
        agent.run.assert_called_once_with("Fix app")
        self.assertIn("Branch: codeagentx/test", output.getvalue())
        self.assertIn("Commit: Fix app", output.getvalue())

    def test_run_subcommand_refuses_commit_after_failed_verification(self) -> None:
        with (
            patch("codeagentx.cli.AgentLoop") as agent_loop,
            patch("codeagentx.cli._git_checked") as git_checked,
        ):
            agent = agent_loop.return_value
            agent.last_state = SimpleNamespace(
                task_id="task-1",
                verification_report={"status": "failed", "summary": "tests failed"},
            )
            stderr = io.StringIO()

            with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                exit_code = cli.main([
                    "run",
                    "--provider",
                    "mock",
                    "--model",
                    "mock-model",
                    "--no-trajectory",
                    "--commit",
                    "Fix",
                    "app",
                ])

        self.assertEqual(exit_code, 1)
        git_checked.assert_not_called()
        self.assertIn("refusing to commit because verification failed", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
