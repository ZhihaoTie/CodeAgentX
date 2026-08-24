"""Verify that a stuck runtime run is failed by the control plane timeout.

This smoke proves a V2 reliability property:

    runtime keeps returning RUNNING -> control plane marks the run FAILED

Start the control plane with a short timeout before running this script:

    cd control-plane
    $env:CODEAGENTX_RUNTIME_RUN_TIMEOUT_MS="1000"
    mvn spring-boot:run "-Dspring-boot.run.profiles=smoke"

The script starts a fake runtime on 127.0.0.1:8765 that never completes runs.
"""

from __future__ import annotations

import json
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen
from uuid import uuid4


CONTROL_PLANE_URL = "http://127.0.0.1:8080"
FAKE_RUNTIME_HOST = "127.0.0.1"
FAKE_RUNTIME_PORT = 8765


class StuckRuntimeStore:
    def __init__(self) -> None:
        self.runs: dict[str, dict[str, Any]] = {}
        self.lock = threading.RLock()

    def create(self, task: str) -> dict[str, Any]:
        run_id = "stuck-runtime-" + uuid4().hex[:8]
        record = {
            "run_id": run_id,
            "task": task,
            "status": "RUNNING",
            "final_text": None,
            "error": None,
            "patch_diff": None,
            "test_report": None,
            "changed_files": None,
            "trajectory_report_path": None,
        }
        with self.lock:
            self.runs[run_id] = record
        return record

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self.lock:
            record = self.runs.get(run_id)
            return dict(record) if record else None


class StuckRuntimeHandler(BaseHTTPRequestHandler):
    server: "StuckRuntimeServer"

    def do_GET(self) -> None:
        parts = [part for part in self.path.split("/") if part]
        if self.path == "/health":
            self._send_json({"status": "ok"})
            return
        if len(parts) == 3 and parts[:2] == ["internal", "runs"]:
            record = self.server.store.get(parts[2])
            if record is None:
                self._send_json({"error": "run not found"}, HTTPStatus.NOT_FOUND)
                return
            self._send_json(record)
            return
        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path != "/internal/runs":
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        payload = self._read_json()
        task = str(payload.get("task") or "").strip()
        if not task:
            self._send_json({"error": "task required"}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json(self.server.store.create(task), HTTPStatus.ACCEPTED)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw.strip() else {}

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class StuckRuntimeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        self.store = StuckRuntimeStore()
        super().__init__((FAKE_RUNTIME_HOST, FAKE_RUNTIME_PORT), StuckRuntimeHandler)


def post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def get_json(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_failed(run_id: str, timeout_seconds: float = 20.0) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last: dict[str, Any] | None = None
    while time.time() < deadline:
        last = get_json(f"{CONTROL_PLANE_URL}/api/runs/{run_id}")
        print(f"run {run_id}: {last.get('status')} {last.get('failureReason') or ''}")
        if last.get("status") == "FAILED":
            return last
        if last.get("status") in {"NEEDS_REVIEW", "SUCCEEDED", "CANCELLED"}:
            raise RuntimeError(f"run reached unexpected terminal/review state: {last}")
        time.sleep(0.5)
    raise RuntimeError(f"timed out waiting for FAILED; last={last}")


def main() -> int:
    server = StuckRuntimeServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"stuck fake runtime listening on http://{FAKE_RUNTIME_HOST}:{FAKE_RUNTIME_PORT}")

    try:
        health = get_json(f"{CONTROL_PLANE_URL}/api/health")
        print("health:", json.dumps(health, ensure_ascii=False))
        created = post_json(
            f"{CONTROL_PLANE_URL}/api/tasks",
            {
                "source": "timeout-smoke",
                "title": "Timeout stuck runtime run",
                "body": "The fake runtime intentionally keeps this run in RUNNING.",
                "idempotencyKey": "timeout-smoke-" + uuid4().hex[:8],
                "repositoryFullName": "acme/repo",
                "baseBranch": "main",
            },
        )
    except URLError as exc:
        print("control plane is not reachable.")
        print('Start it with a short timeout: cd control-plane; $env:CODEAGENTX_RUNTIME_RUN_TIMEOUT_MS="1000"; mvn spring-boot:run "-Dspring-boot.run.profiles=smoke"')
        raise SystemExit(2) from exc

    run_id = created["runId"]
    print("created run:", run_id)
    failed = wait_for_failed(run_id)
    failure_reason = str(failed.get("failureReason") or "")
    if "timed out" not in failure_reason:
        raise RuntimeError(f"expected timeout failure reason, got: {failed}")
    print("timeout smoke succeeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())