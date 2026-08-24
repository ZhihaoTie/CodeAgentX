"""Task session metadata for a single CodeAgent-X run."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from codeagentx.config import Config

from .state import AgentState, utc_now_iso


@dataclass
class RunSession:
    """Owns the durable identity and runtime metadata for one task run."""

    objective: str
    config: Config
    provider_name: str
    state: AgentState = field(init=False)
    session_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        self.state = AgentState(goal=self.objective)
        self.state.start()

    @property
    def workspace_root(self) -> str:
        return str(Path(self.config.workspace_root).expanduser().resolve())

    @property
    def permission_mode(self) -> str:
        return self.config.permission_mode.value

    @property
    def model(self) -> str:
        return self.config.model

    @property
    def verification_command(self) -> str | None:
        return self.config.verification_command

    def start_event_payload(self) -> dict[str, Any]:
        """Return non-secret metadata suitable for trajectory events."""

        return {
            "session_id": self.session_id,
            "task_id": self.state.task_id,
            "goal": self.objective,
            "provider": self.provider_name,
            "model": self.model,
            "workspace_root": self.workspace_root,
            "permission_mode": self.permission_mode,
            "verification_command": self.verification_command,
            "created_at": self.created_at,
            "max_turns": self.config.max_turns,
            "max_tool_calls": getattr(self.config, "max_tool_calls", None),
            "max_run_seconds": getattr(self.config, "max_run_seconds", None),
            "enable_runtime_planning": self.config.enable_runtime_planning,
            "enable_context_ranking": self.config.enable_context_ranking,
            "enable_patch_policy": self.config.enable_patch_policy,
            "enable_sandbox_artifacts": self.config.enable_sandbox_artifacts,
            "enable_tool_planning_guidance": self.config.enable_tool_planning_guidance,
            "max_reflection_retries": self.config.max_reflection_retries,
        }
