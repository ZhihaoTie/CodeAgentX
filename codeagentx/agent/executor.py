"""Tool execution bridge for the CodeAgent-X runtime."""

from __future__ import annotations

from typing import Any
from time import perf_counter

from codeagentx.config import Config
from codeagentx.permissions import PermissionGate
from codeagentx.tools.base import ToolRegistry

from .state import AgentAction, AgentObservation, AgentState


class ToolExecutor:
    """Executes runtime actions through the shared tool registry and permission gate."""

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        config: Config | None = None,
        permission_gate: PermissionGate | None = None,
    ) -> None:
        self.registry = registry or ToolRegistry.default()
        self.config = config or Config()
        self.permission_gate = permission_gate or PermissionGate(self.config)

    def execute(self, action: AgentAction) -> AgentObservation:
        started = perf_counter()
        tool = self.registry.get(action.tool_name)
        if tool is None:
            return self._observation(
                action.tool_name,
                output=f"Error: unknown tool '{action.tool_name}'",
                is_error=True,
                started=started,
            )

        params = dict(action.tool_input)
        denial = self.permission_gate.check(tool, params)
        permission_metadata = _pop_permission_metadata(params)
        if denial is not None:
            return self._observation(
                action.tool_name,
                output=denial.output,
                is_error=True,
                started=started,
                metadata=permission_metadata,
            )

        tool_params = _public_tool_params(params)
        try:
            result = tool.execute(tool_params)
        except Exception as exc:
            return self._observation(
                action.tool_name,
                output=f"Error: tool execution raised {exc.__class__.__name__}: {exc}",
                is_error=True,
                started=started,
                metadata=permission_metadata,
            )

        return self._observation(
            action.tool_name,
            output=result.output,
            is_error=result.is_error,
            started=started,
            metadata=_merge_metadata(permission_metadata, dict(result.metadata)),
        )

    def execute_and_record(self, state: AgentState, action: AgentAction) -> AgentObservation:
        observation = self.execute(action)
        state.add_step(action, observation)
        return observation

    @staticmethod
    def _observation(
        tool_name: str,
        output: str,
        is_error: bool,
        started: float,
        metadata: dict[str, Any] | None = None,
    ) -> AgentObservation:
        duration_ms = round((perf_counter() - started) * 1000, 3)
        observation_metadata: dict[str, Any] = {"duration_ms": duration_ms}
        if metadata:
            observation_metadata.update(metadata)
        return AgentObservation(
            tool_name=tool_name,
            output=output,
            is_error=is_error,
            metadata=observation_metadata,
        )


def _pop_permission_metadata(params: dict[str, Any]) -> dict[str, Any]:
    permission = params.pop("_permission", None)
    if isinstance(permission, dict) and permission:
        return {"permission": permission}
    return {}


def _public_tool_params(params: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in params.items() if not str(key).startswith("_")}


def _merge_metadata(*items: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for item in items:
        merged.update(item)
    return merged
