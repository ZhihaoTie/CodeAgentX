"""Verify that transient runtime submission failures are retried by the control plane.

This smoke proves a V2 reliability property:

    runtime submit fails briefly -> control plane retries -> run continues

Start the control plane with submit retries enabled before running this script:

    cd control-plane
    $env:CODEAGENTX_RUNTIME_SUBMIT_MAX_ATTEMPTS="3"
    $env:CODEAGENTX_RUNTIME_SUBMIT_RETRY_BACKOFF_MS="100"
    mvn spring-boot:run "-Dspring-boot.run.profiles=smoke"

The script starts a fake runtime on 127.0.0.1:8765 that returns HTTP 503 for
the first two submit attempts and then accepts the run.
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
FAILURES_BEFORE_SUCCESS = 2


class RetryRuntimeStore:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.submit_attempts = 0
        self.runs: dict[str, dict[str, Any]] = {}

    def create(self, task: str) -> tuple[HTTPStatus, dict[str, Any]]:
        with self.lock:
            self.submit_attempts += 1
            attempt = self.submit_attempts
        if attempt <= FAILURES_BEFORE_SUCCESS:
            return HTTPStatus.SERVICE_UNAVAILABLE, {
                "error": "transient runtime outage",
                "attempt": attempt,
            }
        run_id = "retry-runtime-" + uuid4().hex[:8]
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
        return HTTPStatus.ACCEPTED, record

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self.lock:
            record = self.runs.get(run_id)
            return dict(record) if record else None

    def stats(self) -> dict[str, int]:
        with self.lock:
            return {"submitAttempts": self.submit_attempts}


class RetryRuntimeHandler(BaseHTTPRequestHandler):
    server: "RetryRuntimeServer"

    def do_GET(self) -> None:
        parts = [part for part in self.path.split("/") if part]
        if self.path == "/health":
            self._send_json({"status": "ok"})
            return
        if self.path == "/stats":
            self._send_json(self.server.store.stats())
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
        status, response = self.server.store.create(task)
        self._send_json(response, status)

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


class RetryRuntimeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        self.store = RetryRuntimeStore()
        super().__init__((FAKE_RUNTIME_HOST, FAKE_RUNTIME_PORT), RetryRuntimeHandler)


def post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def get_json(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_runtime_run_id(run_id: str, timeout_seconds: float = 10.0) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last: dict[str, Any] | None = None
    while time.time() < deadline:
        last = get_json(f"{CONTROL_PLANE_URL}/api/runs/{run_id}")
        print(f"run {run_id}: {last.get('status')} runtime={last.get('runtimeRunId')}")
        if last.get("runtimeRunId"):
            return last
        if last.get("status") in {"FAILED", "CANCELLED"}:
            raise RuntimeError(f"run failed before retry success: {last}")
        time.sleep(0.25)
    raise RuntimeError(f"timed out waiting for runtimeRunId; last={last}")


def main() -> int:
    server = RetryRuntimeServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"retry fake runtime listening on http://{FAKE_RUNTIME_HOST}:{FAKE_RUNTIME_PORT}")

    try:
        health = get_json(f"{CONTROL_PLANE_URL}/api/health")
        print("health:", json.dumps(health, ensure_ascii=False))
        created = post_json(
            f"{CONTROL_PLANE_URL}/api/tasks",
            {
                "source": "retry-smoke",
                "title": "Retry transient runtime submit failure",
                "body": "The fake runtime fails the first two submit attempts.",
                "idempotencyKey": "retry-smoke-" + uuid4().hex[:8],
                "repositoryFullName": "acme/repo",
                "baseBranch": "main",
            },
        )
    except URLError as exc:
        print("control plane is not reachable.")
        print('Start it with: cd control-plane; $env:CODEAGENTX_RUNTIME_SUBMIT_MAX_ATTEMPTS="3"; $env:CODEAGENTX_RUNTIME_SUBMIT_RETRY_BACKOFF_MS="100"; mvn spring-boot:run "-Dspring-boot.run.profiles=smoke"')
        raise SystemExit(2) from exc

    run_id = created["runId"]
    print("created run:", run_id)
    run = wait_for_runtime_run_id(run_id)
    stats = server.store.stats()
    if stats["submitAttempts"] != FAILURES_BEFORE_SUCCESS + 1:
        raise RuntimeError(f"expected 3 submit attempts, got: {stats}")
    if run.get("status") not in {"RUNNING", "REVISING", "NEEDS_REVIEW"}:
        raise RuntimeError(f"unexpected run status after retry success: {run}")
    print("runtime submit retry smoke succeeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())