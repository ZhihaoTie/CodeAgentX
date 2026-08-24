"""Local smoke demo for the CodeAgent-X 2.0 control plane.

This script starts a deterministic fake Python runtime service and drives a
running Spring Boot control plane through:

    POST /api/tasks
      -> NEEDS_REVIEW
      -> AUTHORIZE_PR
      -> PR_CREATED
      -> workflow_run webhook
      -> SUCCEEDED

Start the control plane separately before running this script:

    cd control-plane
    mvn spring-boot:run

The control plane should use the default runtime URL:

    http://127.0.0.1:8765
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


class FakeRuntimeStore:
    def __init__(self) -> None:
        self.runs: dict[str, dict[str, Any]] = {}
        self.lock = threading.RLock()

    def create(self, task: str) -> dict[str, Any]:
        run_id = "fake-runtime-" + uuid4().hex[:8]
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
        threading.Thread(target=self._complete, args=(run_id,), daemon=True).start()
        return record

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self.lock:
            record = self.runs.get(run_id)
            return dict(record) if record else None

    def _complete(self, run_id: str) -> None:
        time.sleep(0.5)
        with self.lock:
            record = self.runs[run_id]
            record.update({
                "status": "SUCCEEDED",
                "final_text": "Fake runtime produced a reviewable patch artifact.",
                "patch_diff": "diff --git a/app.py b/app.py\n+fixed by CodeAgent-X smoke demo\n",
                "test_report": json.dumps({"status": "passed", "summary": "fake tests passed"}),
                "changed_files": "app.py",
                "trajectory_report_path": ".codeagentx/smoke/fake-trajectory.json",
            })


class FakeRuntimeHandler(BaseHTTPRequestHandler):
    server: "FakeRuntimeServer"

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


class FakeRuntimeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        self.store = FakeRuntimeStore()
        super().__init__((FAKE_RUNTIME_HOST, FAKE_RUNTIME_PORT), FakeRuntimeHandler)


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    request = Request(url, data=data, headers=request_headers, method="POST")
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def get_json(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_status(run_id: str, expected: set[str], timeout_seconds: float = 20.0) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last: dict[str, Any] | None = None
    while time.time() < deadline:
        last = get_json(f"{CONTROL_PLANE_URL}/api/runs/{run_id}")
        print(f"run {run_id}: {last.get('status')}")
        if last.get("status") in expected:
            return last
        time.sleep(1)
    raise RuntimeError(f"timed out waiting for {expected}; last={last}")


def send_workflow_run_webhook(run: dict[str, Any], status: str, conclusion: str | None) -> dict[str, Any]:
    patch_branch = run.get("patchBranch")
    if not patch_branch:
        raise RuntimeError(f"run has no patchBranch for CI writeback: {run}")
    return post_json(
        f"{CONTROL_PLANE_URL}/api/webhooks/github",
        {
            "workflow_run": {
                "head_branch": patch_branch,
                "status": status,
                "conclusion": conclusion,
                "html_url": "https://github.com/acme/repo/actions/runs/smoke",
            }
        },
        headers={
            "X-GitHub-Event": "workflow_run",
            "X-GitHub-Delivery": "smoke-ci-" + uuid4().hex[:8],
        },
    )


def main() -> int:
    server = FakeRuntimeServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"fake runtime listening on http://{FAKE_RUNTIME_HOST}:{FAKE_RUNTIME_PORT}")

    try:
        get_json(f"{CONTROL_PLANE_URL}/api/runs/not-found")
    except Exception:
        pass

    try:
        created = post_json(
            f"{CONTROL_PLANE_URL}/api/tasks",
            {
                "source": "smoke",
                "title": "Smoke demo task",
                "body": "Exercise task -> runtime -> review -> noop PR -> CI writeback.",
                "idempotencyKey": "smoke-" + uuid4().hex[:8],
                "repositoryFullName": "acme/repo",
                "baseBranch": "main",
            },
        )
    except URLError as exc:
        print("control plane is not reachable.")
        print("Start it first: cd control-plane; mvn spring-boot:run -Dspring-boot.run.profiles=smoke")
        raise SystemExit(2) from exc

    run_id = created["runId"]
    print(f"created run: {run_id}")

    reviewed = wait_for_status(run_id, {"NEEDS_REVIEW", "FAILED"})
    if reviewed.get("status") != "NEEDS_REVIEW":
        raise RuntimeError(f"run did not reach review: {reviewed}")

    authorized = post_json(
        f"{CONTROL_PLANE_URL}/api/runs/{run_id}/review",
        {
            "decision": "AUTHORIZE_PR",
            "comment": "Smoke demo authorization.",
        },
    )
    if authorized.get("status") != "PR_CREATED":
        raise RuntimeError(f"expected PR_CREATED, got {authorized}")

    ci_running = send_workflow_run_webhook(authorized, "in_progress", None)
    if ci_running.get("status") != "CI_RUNNING":
        raise RuntimeError(f"expected CI_RUNNING, got {ci_running}")

    completed = send_workflow_run_webhook(authorized, "completed", "success")
    if completed.get("status") != "SUCCEEDED":
        raise RuntimeError(f"expected SUCCEEDED, got {completed}")

    print("smoke demo succeeded")
    print("pullRequestUrl:", completed.get("pullRequestUrl"))
    print("patchBranch:", completed.get("patchBranch"))
    print("patchCommitSha:", completed.get("patchCommitSha"))
    print("patchPushedRef:", completed.get("patchPushedRef"))
    print("changedFiles:", (completed.get("patchArtifact") or {}).get("changedFiles"))
    print("finalStatus:", completed.get("status"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
