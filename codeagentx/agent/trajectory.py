"""Trajectory recording boundary for CodeAgent-X runs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from codeagentx.storage import TrajectoryStore

from .state import AgentState


class TrajectoryRecorder:
    """Persist run events and snapshots when trajectory storage is configured."""

    def __init__(self, store: TrajectoryStore | None = None) -> None:
        self.store = store

    def record(
        self,
        state: AgentState,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        if self.store is None:
            return
        self.store.record_state(state, event_type, payload)
