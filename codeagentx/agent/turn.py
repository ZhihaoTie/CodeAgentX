"""Single-turn tool execution for CodeAgent-X."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any, Callable, TextIO

from codeagentx.context import ConversationContext
from codeagentx.terminal import write_text

from .executor import ToolExecutor
from .guidance import ToolGuidanceCheck
from .state import AgentAction, AgentObservation, AgentState


GuidanceCallback = Callable[[AgentState, AgentAction], ToolGuidanceCheck | None]
ObservationCallback = Callable[[AgentState, AgentAction, AgentObservation], None]


@dataclass(frozen=True)
class ToolTurnResult:
    """Structured result from executing a batch of model-requested tool calls."""

    observations: list[AgentObservation] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)

    @property
    def failed_tool_calls(self) -> int:
        return sum(1 for observation in self.observations if observation.is_error)


class TurnRunner:
    """Executes tool calls for one model turn and appends tool results to context."""

    def __init__(
        self,
        *,
        tool_executor: ToolExecutor,
        context: ConversationContext,
        guidance_callback: GuidanceCallback | None = None,
        observation_callback: ObservationCallback | None = None,
        output: TextIO | None = None,
    ) -> None:
        self.tool_executor = tool_executor
        self.context = context
        self.guidance_callback = guidance_callback
        self.observation_callback = observation_callback
        self.output = output

    def execute_tool_calls(
        self,
        tool_calls: list[dict[str, Any]],
        state: AgentState,
    ) -> ToolTurnResult:
        """Execute tool calls, record state steps, and append provider tool results."""

        observations: list[AgentObservation] = []
        tool_results: list[dict[str, Any]] = []
        for call in tool_calls:
            action = AgentAction(
                tool_name=str(call.get("name", "")),
                tool_input=call.get("input") or {},
                rationale="llm_tool_use",
            )
            observation = self._execute_action(state, action)
            state.add_step(action, observation)
            observations.append(observation)

            if self.observation_callback is not None:
                self.observation_callback(state, action, observation)

            self._write_observation_preview(observation)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": call.get("id"),
                "content": observation.output,
                "is_error": observation.is_error,
            })

        self.context.add_tool_results(tool_results)
        return ToolTurnResult(observations=observations, tool_results=tool_results)

    def _execute_action(
        self,
        state: AgentState,
        action: AgentAction,
    ) -> AgentObservation:
        guidance_check = (
            self.guidance_callback(state, action)
            if self.guidance_callback is not None
            else None
        )
        if guidance_check is not None and guidance_check.blocked:
            return _blocked_guidance_observation(action, guidance_check)

        observation = self.tool_executor.execute(action)
        if guidance_check is not None and guidance_check.warning:
            return _observation_with_guidance(observation, guidance_check)
        return observation

    def _write_observation_preview(self, observation: AgentObservation) -> None:
        output_preview = observation.output
        if len(output_preview) > 300:
            output_preview = output_preview[:300] + "... "
        status = "ERROR" if observation.is_error else "OK"
        output = self.output if self.output is not None else sys.stdout
        write_text(f"  -> [{status}] {output_preview}\n", output)


def _blocked_guidance_observation(
    action: AgentAction,
    check: ToolGuidanceCheck,
) -> AgentObservation:
    return AgentObservation(
        tool_name=action.tool_name,
        output=f"Blocked by retry planning guidance: {check.reason}",
        is_error=True,
        metadata={
            "duration_ms": 0.0,
            "tool_planning_guidance": check.to_dict(),
        },
    )


def _observation_with_guidance(
    observation: AgentObservation,
    check: ToolGuidanceCheck,
) -> AgentObservation:
    metadata = dict(observation.metadata)
    metadata["tool_planning_guidance"] = check.to_dict()
    return AgentObservation(
        tool_name=observation.tool_name,
        output=observation.output,
        is_error=observation.is_error,
        metadata=metadata,
    )
