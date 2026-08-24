"""Verify that the control plane respects the configured worker concurrency limit.

This smoke proves a V2 reliability property:

    many tasks arrive together -> runtime submissions are bounded by worker size

Start the control plane with a single worker before running this script:

    cd control-plane
    $env:CODEAGENTX_WORKER_CORE_POOL_SIZE="1"
    $env:CODEAGENTX_WORKER_MAX_POOL_SIZE="1"
    $env:CODEAGENTX_WORKER_QUEUE_CAPACITY="10"
    mvn spring-boot:run "-Dspring-boot.run.profiles=smoke"

The script starts a fake runtime on 127.0.0.1:8765. Each runtime submission
blocks briefly so overlapping submissions would be observable if the control
plane exceeded the configured worker concurrency.
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
TASK_COUNT = 3
EXPECTED_MAX_CONCURRENT_SUBMISSIONS = 1


class ConcurrencyRuntimeStore:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.runs: dict[str, dict[str, Any]] = {}
        self.active_submissions = 0
        self.max_active_submissions = 0
        self.total_submissions = 0

    def create(self, task: str) -> dict[str, Any]:
        run_id = "concurrency-runtime-" + uuid4().hex[:8]
        with self.lock:
            self.active_submissions += 1
            self.total_submissions += 1
            self.max_active_submissions = max(self.max_active_submissions, self.active_submissions)
        try:
            time.sleep(1.0)
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
        finally:
            with self.lock:
                self.active_submissions -= 1

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self.lock:
            record = self.runs.get(run_id)
            return dict(record) if record else None

    def stats(self) -> dict[str, int]:
        with self.lock:
            return {
                "activeSubmissions": self.active_submissions,
                "maxActiveSubmissions": self.max_active_submissions,
                "totalSubmissions": self.total_submissions,
            }


class ConcurrencyRuntimeHandler(BaseHTTPRequestHandler):
    server: "ConcurrencyRuntimeServer"

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


class ConcurrencyRuntimeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        self.store = ConcurrencyRuntimeStore()
        super().__init__((FAKE_RUNTIME_HOST, FAKE_RUNTIME_PORT), ConcurrencyRuntimeHandler)


def post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def get_json(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def submit_task(index: int, results: list[dict[str, Any]], errors: list[BaseException]) -> None:
    try:
        created = post_json(
            f"{CONTROL_PLANE_URL}/api/tasks",
            {
                "source": "concurrency-smoke",
                "title": f"Concurrency task {index}",
                "body": "The fake runtime blocks submissions so worker concurrency is observable.",
                "idempotencyKey": "concurrency-smoke-" + uuid4().hex[:8],
                "repositoryFullName": "acme/repo",
                "baseBranch": "main",
            },
        )
        results.append(created)
    except BaseException as exc:
        errors.append(exc)


def wait_for_submissions(server: ConcurrencyRuntimeServer, expected: int, timeout_seconds: float = 15.0) -> dict[str, int]:
    deadline = time.time() + timeout_seconds
    stats = server.store.stats()
    while time.time() < deadline:
        stats = server.store.stats()
        print("runtime stats:", json.dumps(stats))
        if stats["totalSubmissions"] >= expected and stats["activeSubmissions"] == 0:
            return stats
        time.sleep(0.25)
    raise RuntimeError(f"timed out waiting for submissions; stats={stats}")


def main() -> int:
    server = ConcurrencyRuntimeServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"concurrency fake runtime listening on http://{FAKE_RUNTIME_HOST}:{FAKE_RUNTIME_PORT}")

    try:
        health = get_json(f"{CONTROL_PLANE_URL}/api/health")
        print("health:", json.dumps(health, ensure_ascii=False))
    except URLError as exc:
        print("control plane is not reachable.")
        print('Start it with: cd control-plane; $env:CODEAGENTX_WORKER_CORE_POOL_SIZE="1"; $env:CODEAGENTX_WORKER_MAX_POOL_SIZE="1"; mvn spring-boot:run "-Dspring-boot.run.profiles=smoke"')
        raise SystemExit(2) from exc

    results: list[dict[str, Any]] = []
    errors: list[BaseException] = []
    threads = [threading.Thread(target=submit_task, args=(index, results, errors)) for index in range(TASK_COUNT)]
    for task_thread in threads:
        task_thread.start()
    for task_thread in threads:
        task_thread.join(timeout=10)

    if errors:
        raise RuntimeError(f"task submission failed: {errors[0]}")
    if len(results) != TASK_COUNT:
        raise RuntimeError(f"expected {TASK_COUNT} created tasks, got {len(results)}")

    stats = wait_for_submissions(server, TASK_COUNT)
    max_active = stats["maxActiveSubmissions"]
    if max_active > EXPECTED_MAX_CONCURRENT_SUBMISSIONS:
        raise RuntimeError(
            f"worker concurrency limit was exceeded: max_active={max_active}; "
            f"expected <= {EXPECTED_MAX_CONCURRENT_SUBMISSIONS}"
        )
    print("concurrency limit smoke succeeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
