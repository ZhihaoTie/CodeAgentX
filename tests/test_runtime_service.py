import json
import time
import unittest
from unittest.mock import patch

from codeagentx.agent.state import AgentAction, AgentObservation, AgentState
from codeagentx.service import RuntimeRunStatus, RuntimeService


class RuntimeServiceTests(unittest.TestCase):
    def test_rejects_empty_task(self):
        service = RuntimeService()

        with self.assertRaisesRegex(ValueError, "task"):
            service.submit({"task": "  "})

    def test_runs_agent_in_background_and_records_result(self):
        class FakeAgent:
            def __init__(self, config):
                self.config = config
                self.last_state = None

            def run(self, task):
                self.last_state = AgentState(goal=task)
                action = AgentAction(
                    tool_name="edit_file",
                    tool_input={"path": "app.py"},
                )
                observation = AgentObservation(
                    tool_name="edit_file",
                    output="edited app.py",
                    metadata={
                        "patch": {
                            "path": "app.py",
                            "diff": "diff --git a/app.py b/app.py\n+fixed\n",
                        }
                    },
                )
                self.last_state.add_step(action, observation)
                self.last_state.set_verification_report({
                    "status": "passed",
                    "summary": "pytest passed",
                })
                self.last_state.finish()
                return "done"

        with patch("codeagentx.service.runtime_api.AgentLoop", FakeAgent):
            service = RuntimeService()
            record = service.submit({
                "task": "Fix the bug",
                "provider": "mock",
                "permission_mode": "auto",
                "max_turns": 1,
            })

            deadline = time.time() + 2
            while time.time() < deadline:
                latest = service.store.get(record.run_id)
                if latest and latest.status == RuntimeRunStatus.SUCCEEDED:
                    break
                time.sleep(0.01)

        latest = service.store.get(record.run_id)
        self.assertIsNotNone(latest)
        self.assertEqual(latest.status, RuntimeRunStatus.SUCCEEDED)
        self.assertEqual(latest.final_text, "done")
        self.assertEqual(latest.state["status"], "succeeded")
        self.assertIn("diff --git", latest.patch_diff)
        self.assertEqual(latest.changed_files, "app.py")
        self.assertIn("pytest passed", latest.test_report)
        self.assertEqual(
            [event["event_type"] for event in latest.events],
            ["RUN_QUEUED", "RUN_STARTED", "RUN_FINISHED"],
        )

    def test_records_agent_failure(self):
        class FailingAgent:
            def __init__(self, config):
                self.config = config

            def run(self, task):
                raise RuntimeError("boom")

        with patch("codeagentx.service.runtime_api.AgentLoop", FailingAgent):
            service = RuntimeService()
            record = service.submit({"task": "Fix the bug"})

            deadline = time.time() + 2
            while time.time() < deadline:
                latest = service.store.get(record.run_id)
                if latest and latest.status == RuntimeRunStatus.FAILED:
                    break
                time.sleep(0.01)

        latest = service.store.get(record.run_id)
        self.assertIsNotNone(latest)
        self.assertEqual(latest.status, RuntimeRunStatus.FAILED)
        self.assertIn("RuntimeError", latest.error)
        self.assertEqual(latest.events[-1]["event_type"], "RUN_FAILED")


class RuntimeRecordTests(unittest.TestCase):
    def test_record_serializes_events_when_requested(self):
        service = RuntimeService()
        record = service.store.create("Fix the bug")

        without_events = record.to_dict()
        with_events = record.to_dict(include_events=True)

        json.dumps(without_events)
        json.dumps(with_events)
        self.assertNotIn("events", without_events)
        self.assertEqual(with_events["events"][0]["event_type"], "RUN_QUEUED")
