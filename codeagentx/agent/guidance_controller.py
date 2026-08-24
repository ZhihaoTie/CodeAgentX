"""Runtime tool-guidance state for CodeAgent-X retries."""

from __future__ import annotations

from typing import Any, Callable

from .guidance import ToolGuidanceCheck, ToolGuidanceStatus, ToolPlanningGuidance
from .state import AgentAction, AgentState


RecordEvent = Callable[[AgentState, str, dict[str, Any]], None]


class ToolGuidanceController:
    """Owns the active retry guidance and per-action checks."""

    def __init__(
        self,
        *,
        record_event: RecordEvent,
        active_guidance: ToolPlanningGuidance | None = None,
    ) -> None:
        self.record_event = record_event
        self.active_guidance = active_guidance

    def reset(self) -> None:
        self.active_guidance = None

    def set_guidance(self, guidance: ToolPlanningGuidance | None) -> None:
        self.active_guidance = guidance

    def check(
        self,
        state: AgentState,
        action: AgentAction,
    ) -> ToolGuidanceCheck | None:
        guidance = self.active_guidance
        if guidance is None:
            return None

        check = guidance.evaluate(action)
        if check.status != ToolGuidanceStatus.ALIGNED:
            self.record_event(
                state,
                "tool_planning_guidance_checked",
                {
                    "action": action.to_dict(),
                    "check": check.to_dict(),
                },
            )
        return check
