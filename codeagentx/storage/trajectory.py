"""Persistent trajectory artifacts for agent runs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from codeagentx.agent.state import AgentState, utc_now_iso


SCHEMA_VERSION = "codeagentx.trajectory.v1"


class TrajectoryStore:
    """Stores agent state snapshots and append-only run events."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def state_path(self, task_id: str) -> Path:
        return self.root / f"{task_id}.json"

    def events_path(self, task_id: str) -> Path:
        return self.root / f"{task_id}.jsonl"

    def save_state(self, state: AgentState) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.state_path(state.task_id)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "saved_at": utc_now_iso(),
            "state": state.to_dict(),
        }

        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps(_json_safe(payload), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(path)
        return path

    def record_event(
        self,
        state: AgentState,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
    ) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        event = {
            "schema_version": SCHEMA_VERSION,
            "event_id": str(uuid4()),
            "task_id": state.task_id,
            "event_type": event_type,
            "created_at": utc_now_iso(),
            "payload": dict(payload or {}),
        }
        path = self.events_path(state.task_id)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(_json_safe(event), ensure_ascii=False) + "\n")
        return path

    def record_state(
        self,
        state: AgentState,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        self.record_event(state, event_type, payload)
        self.save_state(state)

    def load_state(self, task_id: str) -> dict[str, Any]:
        return json.loads(self.state_path(task_id).read_text(encoding="utf-8"))

    def read_events(self, task_id: str) -> list[dict[str, Any]]:
        path = self.events_path(task_id)
        if not path.exists():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if is_dataclass(value) and hasattr(value, "to_dict"):
        return _json_safe(value.to_dict())

    try:
        json.dumps(value)
    except TypeError:
        return repr(value)
    return value
