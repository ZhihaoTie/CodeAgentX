"""Tests for top-level task-run coordination."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from codeagentx.agent import (
    CompletionResult,
    ModelTurn,
    RunCoordinator,
    ToolPlanningGuidance,
)
from codeagentx.config import Config
from codeagentx.context import ConversationContext
from codeagentx.models import ModelResponse


class _FakeModelTurnController:
    def __init__(
        self,
        turns: list[ModelTurn] | None = None,
        error: BaseException | None = None,
    ):
        self.turns = list(turns or [])
        self.error = error

    def run_turn(self) -> ModelTurn:
        if self.error is not None:
            raise self.error
        return self.turns.pop(0)


class _FakeTurnRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[list[dict], object]] = []

    def execute_tool_calls(self, tool_calls: list[dict], state: object) -> None:
        self.calls.append((tool_calls, state))
        return SimpleNamespace(
            observations=[object() for _tool_call in tool_calls],
        )


class _FakePlanController:
    def __init__(self) -> None:
        self.initialized = False
        self.blocked = False

    def initialize(self, _state: object) -> None:
        self.initialized = True

    def mark_blocked(self, _state: object, _kind: object, *, evidence: str) -> None:
        self.blocked = bool(evidence)


class _FakeCompletionController:
    def __init__(self, completed: bool = True) -> None:
        self.completed = completed

    def complete(self, state: object, _final_text: str) -> CompletionResult:
        state.finish()
        return CompletionResult(
            completed=self.completed,
            active_tool_guidance=None,
        )

    def reflect_failure(self, _state: object, _final_text: str) -> None:
        return None


def _coordinator(
    model_turn_controller: _FakeModelTurnController,
    *,
    max_turns: int = 2,
    max_tool_calls: int | None = None,
):
    events: list[tuple[str, dict]] = []
    sessions: list[object] = []
    active_guidance: list[ToolPlanningGuidance | None] = []
    plan_controller = _FakePlanController()
    completion_controller = _FakeCompletionController()
    config = Config(
        max_turns=max_turns,
        max_tool_calls=max_tool_calls,
        model_provider="mock",
        model="mock-model",
    )
    coordinator = RunCoordinator(
        config=config,
        context=ConversationContext(config=config),
        provider_name="mock",
        model_turn_controller=model_turn_controller,
        turn_runner=_FakeTurnRunner(),
        plan_controller=plan_controller,
        completion_controller=completion_controller,
        record_event=lambda _state, event_type, payload: events.append((event_type, payload)),
        set_active_guidance=active_guidance.append,
        session_callback=sessions.append,
    )
    return coordinator, events, sessions, active_guidance, plan_controller


class RunCoordinatorTests(unittest.TestCase):
    def test_coordinates_successful_single_turn(self):
        model_turn = ModelTurn(
            response=ModelResponse.text("Done.", model="mock-model"),
            text_parts=["Done."],
        )
        coordinator, events, sessions, active_guidance, plan_controller = _coordinator(
            _FakeModelTurnController([model_turn])
        )

        result = coordinator.run("finish the task")

        self.assertEqual(result.final_text, "Done.")
        self.assertEqual(result.state.status.value, "succeeded")
        self.assertIs(result.session, sessions[0])
        self.assertTrue(plan_controller.initialized)
        self.assertEqual(active_guidance, [None, None])
        self.assertEqual(
            [event_type for event_type, _payload in events[:2]],
            ["task_started", "model_response"],
        )
        self.assertEqual(events[-1][0], "run_budget_completed")
        self.assertEqual(events[-1][1]["turns"], 1)

    def test_model_error_is_recorded_and_re_raised(self):
        coordinator, events, sessions, _active_guidance, _plan_controller = _coordinator(
            _FakeModelTurnController(error=RuntimeError("provider offline"))
        )

        with self.assertRaisesRegex(RuntimeError, "provider offline"):
            coordinator.run("try the task")

        self.assertEqual(sessions[0].state.status.value, "failed")
        self.assertIn(
            "task_failed",
            [event_type for event_type, _payload in events],
        )

    def test_tool_call_budget_stops_before_next_model_turn(self):
        first_turn = ModelTurn(
            response=ModelResponse.tool_use(
                tool_use_id="toolu_1",
                name="read_file",
                tool_input={"path": "app.py"},
                model="mock-model",
            ),
            tool_calls=[{
                "id": "toolu_1",
                "name": "read_file",
                "input": {"path": "app.py"},
            }],
        )
        second_turn = ModelTurn(
            response=ModelResponse.text("Done.", model="mock-model"),
            text_parts=["Done."],
        )
        model = _FakeModelTurnController([first_turn, second_turn])
        coordinator, events, _sessions, _active_guidance, _plan_controller = _coordinator(
            model,
            max_tool_calls=1,
        )

        result = coordinator.run("inspect once")

        self.assertEqual(result.state.status.value, "failed")
        self.assertIn("max tool calls reached", result.state.failure_reason)
        self.assertEqual(len(model.turns), 1)
        self.assertEqual(result.state.run_budget_report["tool_calls"], 1)
        self.assertTrue(result.state.run_budget_report["exhausted"])
        self.assertEqual(
            result.state.run_budget_report["exhausted_reason"],
            "max tool calls reached (1)",
        )
        task_failed = next(
            payload
            for event_type, payload in events
            if event_type == "task_failed"
        )
        self.assertEqual(
            task_failed["budget_reason"],
            "max tool calls reached (1)",
        )

    def test_keyboard_interrupt_cancels_and_records_task(self):
        coordinator, events, sessions, _active_guidance, _plan_controller = _coordinator(
            _FakeModelTurnController(error=KeyboardInterrupt())
        )

        with self.assertRaises(KeyboardInterrupt):
            coordinator.run("interrupt the task")

        self.assertEqual(sessions[0].state.status.value, "cancelled")
        self.assertEqual(sessions[0].state.failure_reason, "run interrupted by user")
        self.assertIn(
            "task_cancelled",
            [event_type for event_type, _payload in events],
        )


if __name__ == "__main__":
    unittest.main()
