"""Tests for the runtime plan controller."""

from __future__ import annotations

import tempfile
import unittest

from codeagentx.agent import AgentAction, AgentObservation, AgentState, PlanController, PlanStepKind
from codeagentx.config import Config, PermissionMode
from codeagentx.context import ConversationContext


class PlanControllerTests(unittest.TestCase):
    def test_initialize_adds_plan_context_and_events(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = Config(
                workspace_root=tempdir,
                permission_mode=PermissionMode.AUTO,
                enable_runtime_planning=True,
            )
            context = ConversationContext(config=config)
            events: list[tuple[str, dict]] = []
            controller = PlanController(
                config=config,
                context=context,
                record_event=lambda _state, event_type, payload: events.append(
                    (event_type, payload)
                ),
            )
            state = AgentState(goal="inspect the project")

            controller.initialize(state)

        self.assertIsNotNone(state.plan)
        self.assertIn("Runtime execution plan:", context.messages[-1]["content"])
        self.assertEqual(
            state.plan.step_by_kind(PlanStepKind.UNDERSTAND_TASK).status.value,
            "done",
        )
        self.assertEqual(
            state.plan.step_by_kind(PlanStepKind.INSPECT_CONTEXT).status.value,
            "in_progress",
        )
        self.assertIn("plan_created", [event_type for event_type, _ in events])
        self.assertIn("plan_step_updated", [event_type for event_type, _ in events])

    def test_tool_observations_and_verification_update_steps(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = Config(
                workspace_root=tempdir,
                permission_mode=PermissionMode.AUTO,
                enable_runtime_planning=True,
                enable_task_constraints=True,
                task_required_changed_paths=["src/app.py"],
            )
            context = ConversationContext(config=config)
            controller = PlanController(
                config=config,
                context=context,
                record_event=lambda *_args: None,
            )
            state = AgentState(goal="change and verify")
            controller.initialize(state)

            controller.update_from_tool_observation(
                state,
                AgentAction(tool_name="read_file", tool_input={"path": "src/app.py"}),
                AgentObservation(tool_name="read_file", output="content"),
            )
            controller.update_from_tool_observation(
                state,
                AgentAction(
                    tool_name="write_file",
                    tool_input={"path": "src/app.py", "content": "updated"},
                ),
                AgentObservation(
                    tool_name="write_file",
                    output="written",
                    metadata={"patch": {"path": "src/app.py"}},
                ),
            )
            controller.update_from_tool_observation(
                state,
                AgentAction(
                    tool_name="bash",
                    tool_input={"command": "python -m unittest tests -v"},
                ),
                AgentObservation(tool_name="bash", output="OK"),
            )
            controller.update_from_verification(
                state,
                {
                    "status": "passed",
                    "summary": "verification passed",
                    "checks": [{"name": "task_constraints", "status": "passed"}],
                },
            )

            assert state.plan is not None
            controller.complete(state, evidence="task finished")

        self.assertTrue(state.plan.is_complete())
        for kind in (
            PlanStepKind.INSPECT_CONTEXT,
            PlanStepKind.MODIFY_WORKSPACE,
            PlanStepKind.VERIFY_OUTCOME,
            PlanStepKind.SATISFY_CONSTRAINTS,
        ):
            step = state.plan.step_by_kind(kind)
            self.assertIsNotNone(step)
            assert step is not None
            self.assertEqual(step.status.value, "done")

    def test_disabled_planning_does_not_mutate_context_or_state(self):
        config = Config(enable_runtime_planning=False)
        context = ConversationContext(config=config)
        controller = PlanController(
            config=config,
            context=context,
            record_event=lambda *_args: self.fail("planning should be disabled"),
        )
        state = AgentState(goal="do nothing")

        controller.initialize(state)

        self.assertIsNone(state.plan)
        self.assertEqual(context.messages, [])


if __name__ == "__main__":
    unittest.main()
