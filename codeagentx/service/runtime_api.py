"""Small internal HTTP API for async CodeAgent-X task execution.

The service intentionally uses only Python's standard library. It gives a Java
control plane a stable protocol before the project commits to a web framework.
"""

from __future__ import annotations

import argparse
import json
import threading
import traceback
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from codeagentx.agent import AgentLoop
from codeagentx.agent.state import utc_now_iso
from codeagentx.config import Config, PermissionMode


class RuntimeRunStatus:
    """Platform-level run statuses exposed by the internal service."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass
class RuntimeRunRecord:
    """One async runtime execution tracked by the internal service."""

    run_id: str
    task: str
    status: str = RuntimeRunStatus.QUEUED
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    final_text: str | None = None
    error: str | None = None
    patch_diff: str | None = None
    test_report: str | None = None
    changed_files: str | None = None
    trajectory_report_path: str | None = None
    agent_task_id: str | None = None
    state: dict[str, Any] | None = None
    events: list[dict[str, Any]] = field(default_factory=list)

    def add_event(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        self.events.append({
            "event_id": str(uuid4()),
            "run_id": self.run_id,
            "event_type": event_type,
            "created_at": utc_now_iso(),
            "payload": dict(payload or {}),
        })
        self.updated_at = utc_now_iso()

    def to_dict(self, *, include_events: bool = False) -> dict[str, Any]:
        payload = {
            "run_id": self.run_id,
            "task": self.task,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "final_text": self.final_text,
            "error": self.error,
            "patch_diff": self.patch_diff,
            "test_report": self.test_report,
            "changed_files": self.changed_files,
            "trajectory_report_path": self.trajectory_report_path,
            "agent_task_id": self.agent_task_id,
            "state": self.state,
        }
        if include_events:
            payload["events"] = list(self.events)
        return payload


class RuntimeRunStore:
    """Thread-safe in-memory run store for the first vertical slice."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._runs: dict[str, RuntimeRunRecord] = {}

    def create(self, task: str) -> RuntimeRunRecord:
        record = RuntimeRunRecord(run_id=str(uuid4()), task=task)
        record.add_event("RUN_QUEUED", {})
        with self._lock:
            self._runs[record.run_id] = record
        return record

    def get(self, run_id: str) -> RuntimeRunRecord | None:
        with self._lock:
            return self._runs.get(run_id)

    def update(self, run_id: str, **changes: Any) -> RuntimeRunRecord:
        with self._lock:
            record = self._runs[run_id]
            for key, value in changes.items():
                setattr(record, key, value)
            record.updated_at = utc_now_iso()
            return record

    def event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            self._runs[run_id].add_event(event_type, payload)


class RuntimeService:
    """Starts AgentLoop work in background threads and tracks run state."""

    def __init__(
        self,
        *,
        store: RuntimeRunStore | None = None,
        base_config: Config | None = None,
    ) -> None:
        self.store = store or RuntimeRunStore()
        self.base_config = base_config or Config.from_env()

    def submit(self, payload: dict[str, Any]) -> RuntimeRunRecord:
        task = str(payload.get("task") or "").strip()
        if not task:
            raise ValueError("request field 'task' is required")

        record = self.store.create(task)
        thread = threading.Thread(
            target=self._run_agent,
            args=(record.run_id, payload),
            name=f"codeagentx-run-{record.run_id[:8]}",
            daemon=True,
        )
        thread.start()
        return record

    def _run_agent(self, run_id: str, payload: dict[str, Any]) -> None:
        self.store.update(run_id, status=RuntimeRunStatus.RUNNING)
        self.store.event(run_id, "RUN_STARTED", {})
        try:
            config = self._config_from_payload(payload)
            agent = AgentLoop(config=config)
            final_text = agent.run(str(payload["task"]))
            state = agent.last_state.to_dict() if agent.last_state is not None else None
            agent_task_id = agent.last_state.task_id if agent.last_state is not None else None
            artifacts = self._artifacts_from_state(
                state,
                trajectory_store=getattr(agent, "trajectory_store", None),
                agent_task_id=agent_task_id,
            )
            status = RuntimeRunStatus.SUCCEEDED
            if state and state.get("status") not in ("succeeded", None):
                status = RuntimeRunStatus.FAILED
            self.store.update(
                run_id,
                status=status,
                final_text=final_text,
                patch_diff=artifacts.get("patch_diff"),
                test_report=artifacts.get("test_report"),
                changed_files=artifacts.get("changed_files"),
                trajectory_report_path=artifacts.get("trajectory_report_path"),
                agent_task_id=agent_task_id,
                state=state,
            )
            self.store.event(run_id, "RUN_FINISHED", {"status": status})
        except Exception as exc:
            self.store.update(
                run_id,
                status=RuntimeRunStatus.FAILED,
                error=f"{exc.__class__.__name__}: {exc}",
            )
            self.store.event(
                run_id,
                "RUN_FAILED",
                {
                    "error_type": exc.__class__.__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exc(limit=20),
                },
            )

    def _config_from_payload(self, payload: dict[str, Any]) -> Config:
        overrides: dict[str, Any] = {}
        if payload.get("provider"):
            overrides["model_provider"] = str(payload["provider"])
        if payload.get("model"):
            overrides["model"] = str(payload["model"])
        if payload.get("workspace_root"):
            overrides["workspace_root"] = str(Path(str(payload["workspace_root"])))
        if payload.get("max_turns") is not None:
            overrides["max_turns"] = int(payload["max_turns"])
        if payload.get("max_run_seconds") is not None:
            overrides["max_run_seconds"] = float(payload["max_run_seconds"])
        if payload.get("verification_command") is not None:
            overrides["verification_command"] = str(payload["verification_command"])
        if payload.get("permission_mode"):
            overrides["permission_mode"] = PermissionMode(str(payload["permission_mode"]))
        return Config.from_env(**{**self.base_config.__dict__, **overrides})

    def _artifacts_from_state(
        self,
        state: dict[str, Any] | None,
        *,
        trajectory_store: Any | None = None,
        agent_task_id: str | None = None,
    ) -> dict[str, str | None]:
        if not state:
            return {
                "patch_diff": None,
                "test_report": None,
                "changed_files": None,
                "trajectory_report_path": None,
            }
        patch_entries = _patch_entries_from_state(state)
        patch_diff = state.get("patch_diff") or state.get("diff") or _join_patch_diffs(patch_entries)
        test_report = (
            state.get("test_report")
            or state.get("verification_report")
            or _latest_test_observation(state)
        )
        changed_files = state.get("changed_files") or _changed_files_from_patches(patch_entries)
        trajectory_report_path = (
            state.get("trajectory_report_path")
            or state.get("report_path")
            or _trajectory_path(trajectory_store, agent_task_id)
        )
        return {
            "patch_diff": _string_or_none(patch_diff),
            "test_report": _jsonish_or_none(test_report),
            "changed_files": _changed_files_text(changed_files),
            "trajectory_report_path": None if trajectory_report_path is None else str(trajectory_report_path),
        }


def _patch_entries_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for step in state.get("trajectory") or []:
        if not isinstance(step, dict):
            continue
        observation = step.get("observation")
        if not isinstance(observation, dict):
            continue
        metadata = observation.get("metadata")
        if not isinstance(metadata, dict):
            continue
        for key in ("patch", "patch_result", "transaction", "result"):
            value = metadata.get(key)
            if isinstance(value, dict) and ("diff" in value or "path" in value):
                entries.append(value)
        patches = metadata.get("patches")
        if isinstance(patches, list):
            entries.extend(item for item in patches if isinstance(item, dict))
    return entries


def _join_patch_diffs(entries: list[dict[str, Any]]) -> str | None:
    diffs = [
        str(entry.get("diff"))
        for entry in entries
        if entry.get("diff")
    ]
    if not diffs:
        return None
    return "\n".join(diffs)


def _changed_files_from_patches(entries: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for entry in entries:
        path = entry.get("path")
        if path is None:
            continue
        text = str(path)
        if text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _latest_test_observation(state: dict[str, Any]) -> str | None:
    for step in reversed(state.get("trajectory") or []):
        if not isinstance(step, dict):
            continue
        action = step.get("action")
        observation = step.get("observation")
        if not isinstance(action, dict) or not isinstance(observation, dict):
            continue
        if action.get("tool_name") != "bash":
            continue
        command = action.get("tool_input", {}).get("command") if isinstance(action.get("tool_input"), dict) else ""
        command_text = str(command or "").lower()
        if any(token in command_text for token in ("test", "pytest", "unittest", "npm", "mvn")):
            return str(observation.get("output") or "")
    return None


def _trajectory_path(
    trajectory_store: Any | None,
    agent_task_id: str | None,
) -> str | None:
    if trajectory_store is None or not agent_task_id:
        return None
    try:
        return str(trajectory_store.state_path(agent_task_id))
    except Exception:
        return None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text.strip() else None


def _jsonish_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return _string_or_none(value)


def _changed_files_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        if not value:
            return None
        return "\n".join(str(item) for item in value)
    return _string_or_none(value)


class RuntimeHTTPRequestHandler(BaseHTTPRequestHandler):
    """HTTP routes for the internal service."""

    server: "RuntimeHTTPServer"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self._send_json({"status": "ok"})
            return

        parts = [part for part in path.split("/") if part]
        if len(parts) >= 3 and parts[:2] == ["internal", "runs"]:
            run_id = parts[2]
            record = self.server.runtime_service.store.get(run_id)
            if record is None:
                self._send_json({"error": "run not found"}, HTTPStatus.NOT_FOUND)
                return
            if len(parts) == 4 and parts[3] == "events":
                self._send_sse(record.events)
                return
            if len(parts) == 3:
                self._send_json(record.to_dict(include_events=True))
                return

        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/internal/runs":
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return

        try:
            payload = self._read_json()
            record = self.server.runtime_service.submit(payload)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        self._send_json(record.to_dict(), HTTPStatus.ACCEPTED)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length).decode("utf-8")
        if not body.strip():
            return {}
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def _send_json(
        self,
        payload: dict[str, Any],
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_sse(self, events: list[dict[str, Any]]) -> None:
        lines: list[str] = []
        for event in events:
            lines.append(f"event: {event['event_type']}")
            lines.append("data: " + json.dumps(event, ensure_ascii=False))
            lines.append("")
        data = ("\n".join(lines) + "\n").encode("utf-8")
        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class RuntimeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        runtime_service: RuntimeService,
    ) -> None:
        self.runtime_service = runtime_service
        super().__init__(server_address, RuntimeHTTPRequestHandler)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the CodeAgent-X internal runtime HTTP service",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    server = RuntimeHTTPServer((args.host, args.port), RuntimeService())
    print(f"CodeAgent-X runtime service listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
