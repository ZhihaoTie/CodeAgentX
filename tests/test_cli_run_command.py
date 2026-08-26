"""Tests for the lightweight local `codeagentx run` entrypoint."""

from __future__ import annotations

import io
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


if __name__ == "__main__":
    unittest.main()
