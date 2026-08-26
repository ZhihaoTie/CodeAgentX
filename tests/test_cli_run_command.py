"""Tests for the lightweight local `codeagentx run` entrypoint."""

from __future__ import annotations

import io
import os
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

    def test_chat_subcommand_rejects_prompt(self) -> None:
        stderr = io.StringIO()

        with redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
            cli.main(["chat", "hello"])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn('the "chat" command does not accept a prompt', stderr.getvalue())

    def test_fix_subcommand_requires_verify(self) -> None:
        stderr = io.StringIO()

        with redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
            cli.main(["fix"])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn('the "fix" command requires --verify', stderr.getvalue())

    def test_fix_subcommand_skips_agent_when_verifier_passes(self) -> None:
        result = SimpleNamespace(passed=True, stdout="", stderr="", exit_code=0)

        with (
            patch("codeagentx.cli.LocalSandboxRunner") as runner,
            patch("codeagentx.cli.AgentLoop") as agent_loop,
        ):
            runner.return_value.run.return_value = result
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = cli.main([
                    "fix",
                    "--provider",
                    "mock",
                    "--verify",
                    "python --version",
                ])

        self.assertEqual(exit_code, 0)
        agent_loop.assert_not_called()
        self.assertIn("verifier already passes", output.getvalue())

    def test_fix_subcommand_injects_failed_verifier_output_into_prompt(self) -> None:
        result = SimpleNamespace(
            passed=False,
            stdout="",
            stderr="AssertionError: expected 1 got 2",
            exit_code=1,
        )

        with (
            patch("codeagentx.cli.LocalSandboxRunner") as runner,
            patch("codeagentx.cli.AgentLoop") as agent_loop,
        ):
            runner.return_value.run.return_value = result
            agent = agent_loop.return_value
            agent.last_state = None

            with redirect_stdout(io.StringIO()):
                exit_code = cli.main([
                    "fix",
                    "--provider",
                    "mock",
                    "--model",
                    "mock-model",
                    "--no-trajectory",
                    "--verify",
                    "pytest -q",
                ])

        self.assertEqual(exit_code, 0)
        prompt = agent.run.call_args.args[0]
        self.assertIn("verification command failed before the agent started", prompt)
        self.assertIn("Command: pytest -q", prompt)
        self.assertIn("AssertionError: expected 1 got 2", prompt)

    def test_doctor_suggests_fix_for_failed_candidate_verifier(self) -> None:
        result = SimpleNamespace(
            passed=False,
            status=SimpleNamespace(value="failed"),
            stdout="",
            stderr="tests failed",
            exit_code=1,
        )

        with (
            patch("codeagentx.cli._candidate_verify_commands", return_value=["pytest -q"]),
            patch("codeagentx.cli.LocalSandboxRunner") as runner,
        ):
            runner.return_value.run.return_value = result
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = cli.main(["doctor", "--provider", "mock"])

        self.assertEqual(exit_code, 1)
        self.assertIn("Candidate verifier commands:", output.getvalue())
        self.assertIn("codeagentx fix --verify", output.getvalue())
        self.assertIn("--yes", output.getvalue())

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

    def test_run_subcommand_pr_requires_commit(self) -> None:
        stderr = io.StringIO()

        with redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
            cli.main(["run", "--pr", "Fix", "app"])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("--pr requires --commit", stderr.getvalue())

    def test_run_subcommand_can_commit_push_and_create_pr(self) -> None:
        git_calls: list[list[str]] = []
        old_token = os.environ.get("CODEAGENTX_GITHUB_TOKEN")
        old_repo = os.environ.get("CODEAGENTX_GITHUB_REPOSITORY")
        os.environ["CODEAGENTX_GITHUB_TOKEN"] = "token"
        os.environ["CODEAGENTX_GITHUB_REPOSITORY"] = "ZhihaoTie/CodeAgentX"

        def git_checked(command, *, cwd):
            git_calls.append(list(command))
            if command == ["git", "branch", "--show-current"]:
                return "codeagentx/test\n"
            if command == ["git", "remote", "get-url", "origin"]:
                return "https://github.com/ZhihaoTie/CodeAgentX.git\n"
            return ""

        try:
            with (
                patch("codeagentx.cli.AgentLoop") as agent_loop,
                patch("codeagentx.cli._git_checked", side_effect=git_checked),
                patch("codeagentx.cli._git_command") as git_command,
                patch("codeagentx.cli._create_github_pull_request", return_value="https://github.com/ZhihaoTie/CodeAgentX/pull/1") as create_pr,
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
                        "--commit",
                        "--pr",
                        "--base",
                        "main",
                        "Fix",
                        "app",
                    ])
        finally:
            _restore_env("CODEAGENTX_GITHUB_TOKEN", old_token)
            _restore_env("CODEAGENTX_GITHUB_REPOSITORY", old_repo)

        self.assertEqual(exit_code, 0)
        self.assertIn(["git", "push", "-u", "origin", "codeagentx/test"], git_calls)
        create_pr.assert_called_once()
        kwargs = create_pr.call_args.kwargs
        self.assertEqual(kwargs["repository"], "ZhihaoTie/CodeAgentX")
        self.assertEqual(kwargs["head"], "codeagentx/test")
        self.assertEqual(kwargs["base"], "main")
        self.assertIn("Pull request: https://github.com/ZhihaoTie/CodeAgentX/pull/1", output.getvalue())

    def test_repository_from_remote_supports_https_and_ssh(self) -> None:
        self.assertEqual(
            cli._repository_from_remote("https://github.com/ZhihaoTie/CodeAgentX.git"),
            "ZhihaoTie/CodeAgentX",
        )
        self.assertEqual(
            cli._repository_from_remote("git@github.com:ZhihaoTie/CodeAgentX.git"),
            "ZhihaoTie/CodeAgentX",
        )


def _restore_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


if __name__ == "__main__":
    unittest.main()
