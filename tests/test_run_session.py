"""Tests for task run session metadata."""

from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from codeagentx.agent import AgentLoop, RunSession
from codeagentx.config import Config, PermissionMode
from codeagentx.models import MockProvider, ModelResponse


def python_command(code: str) -> str:
    return f'"{sys.executable}" -c "{code}"'


class RunSessionTests(unittest.TestCase):
    def test_start_event_payload_contains_runtime_metadata(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = Config(
                model_provider="mock",
                model="mock-model",
                permission_mode=PermissionMode.AUTO,
                workspace_root=tempdir,
                verification_command=python_command("print('ok')"),
            )
            session = RunSession(
                objective="fix the task",
                config=config,
                provider_name="mock",
            )

            payload = session.start_event_payload()

        self.assertEqual(payload["session_id"], session.session_id)
        self.assertEqual(payload["task_id"], session.state.task_id)
        self.assertEqual(payload["goal"], "fix the task")
        self.assertEqual(payload["provider"], "mock")
        self.assertEqual(payload["model"], "mock-model")
        self.assertEqual(payload["permission_mode"], "auto")
        self.assertEqual(payload["verification_command"], python_command("print('ok')"))
        self.assertTrue(Path(payload["workspace_root"]).is_absolute())

    def test_agent_loop_records_session_metadata_on_task_start(self):
        provider = MockProvider([ModelResponse.text("Done.", model="mock-model")])

        with tempfile.TemporaryDirectory() as tempdir:
            workspace = Path(tempdir) / "workspace"
            workspace.mkdir()
            trajectory_dir = Path(tempdir) / "trajectories"
            agent = AgentLoop(
                config=Config(
                    model_provider="mock",
                    model="mock-model",
                    permission_mode=PermissionMode.AUTO,
                    workspace_root=str(workspace),
                    trajectory_dir=str(trajectory_dir),
                    verification_command=python_command("print('ok')"),
                ),
                provider=provider,
            )

            with redirect_stdout(StringIO()):
                agent.run("finish the task")

            state = agent.last_state
            self.assertIsNotNone(state)
            assert state is not None
            events = agent.trajectory_store.read_events(state.task_id)

        self.assertIsNotNone(agent.last_session)
        first = events[0]
        self.assertEqual(first["event_type"], "task_started")
        self.assertEqual(first["payload"]["session_id"], agent.last_session.session_id)
        self.assertEqual(first["payload"]["workspace_root"], str(workspace.resolve()))
        self.assertEqual(first["payload"]["verification_command"], python_command("print('ok')"))


if __name__ == "__main__":
    unittest.main()
