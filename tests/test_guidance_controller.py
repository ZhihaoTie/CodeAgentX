"""Tests for active runtime tool guidance."""

from __future__ import annotations

import tempfile
import unittest

from codeagentx.agent import AgentAction, AgentState, ToolGuidanceController
from codeagentx.agent.guidance import ToolGuidanceStatus, ToolPlanningGuidance
from codeagentx.config import Config
from codeagentx.context import ConversationContext


class ToolGuidanceControllerTests(unittest.TestCase):
    def test_check_records_non_aligned_guidance_events(self):
        events: list[tuple[str, dict]] = []
        controller = ToolGuidanceController(
            record_event=lambda _state, event_type, payload: events.append(
                (event_type, payload)
            ),
            active_guidance=ToolPlanningGuidance(
                strategy="task_constraint_repair",
                retry_index=1,
                preferred_tools=["read_file"],
                blocked_write_patterns=["docs/*"],
                workspace_root=".",
            ),
        )
        state = AgentState(goal="avoid forbidden paths")

        check = controller.check(
            state,
            AgentAction(
                tool_name="write_file",
                tool_input={"path": "docs/notes.md", "content": "blocked"},
            ),
        )

        self.assertEqual(check.status, ToolGuidanceStatus.BLOCKED)
        self.assertEqual(events[0][0], "tool_planning_guidance_checked")
        self.assertEqual(events[0][1]["check"]["status"], "blocked")

    def test_reset_disables_checks(self):
        controller = ToolGuidanceController(
            record_event=lambda *_args: None,
            active_guidance=ToolPlanningGuidance(
                strategy="focused_test_fix",
                retry_index=1,
                preferred_tools=["bash"],
            ),
        )
        state = AgentState(goal="verify")
        action = AgentAction(tool_name="read_file", tool_input={"path": "app.py"})

        controller.reset()

        self.assertIsNone(controller.check(state, action))

    def test_agent_loop_compatibility_field_is_honored(self):
        from codeagentx.agent import AgentLoop

        with tempfile.TemporaryDirectory() as tempdir:
            context = ConversationContext(config=Config(workspace_root=tempdir))
            loop = AgentLoop.__new__(AgentLoop)
            loop.context = context
            loop.trajectory_store = None
            loop.active_tool_guidance = ToolPlanningGuidance(
                strategy="focused_test_fix",
                retry_index=1,
                preferred_tools=["bash"],
            )
            state = AgentState(goal="verify")

            check = loop._check_tool_guidance(
                state,
                AgentAction(tool_name="read_file", tool_input={"path": "app.py"}),
            )

        self.assertEqual(check.status, ToolGuidanceStatus.WARNING)


if __name__ == "__main__":
    unittest.main()
