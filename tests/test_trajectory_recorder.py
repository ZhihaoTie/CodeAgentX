"""Tests for the trajectory recording boundary."""

from __future__ import annotations

import tempfile
import unittest

from codeagentx.agent import AgentState, TrajectoryRecorder
from codeagentx.storage import TrajectoryStore


class TrajectoryRecorderTests(unittest.TestCase):
    def test_records_event_and_snapshot_when_store_is_configured(self):
        with tempfile.TemporaryDirectory() as tempdir:
            state = AgentState(goal="record a run")
            state.start()
            recorder = TrajectoryRecorder(TrajectoryStore(tempdir))

            recorder.record(state, "task_started", {"source": "test"})

            store = recorder.store
            assert store is not None
            events = store.read_events(state.task_id)
            snapshot = store.load_state(state.task_id)

        self.assertEqual(events[0]["event_type"], "task_started")
        self.assertEqual(events[0]["payload"]["source"], "test")
        self.assertEqual(snapshot["state"]["goal"], "record a run")

    def test_without_store_recording_is_a_noop(self):
        state = AgentState(goal="do not persist")

        TrajectoryRecorder().record(state, "task_started", {"source": "test"})

        self.assertEqual(state.goal, "do not persist")


if __name__ == "__main__":
    unittest.main()
