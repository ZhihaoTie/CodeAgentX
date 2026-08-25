#!/usr/bin/env python3
"""Smoke-check Generic REST task intake and result callback delivery in Compose.

This check creates a real control-plane Task/Run but uses the Python runtime's
mock provider so it does not call a paid model or publish to GitHub. It expects
callbacks to be enabled in the running deployment.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class CallbackState:
    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.payloads: list[dict] = []

    def append(self, payload: dict) -> None:
        with self.condition:
            self.payloads.append(payload)
            self.condition.notify_all()

    def wait_for_payload(self, external_task_id: str, timeout_seconds: float) -> dict:
        return self.wait_for_status(external_task_id, None, timeout_seconds)

    def wait_for_status(self, external_task_id: str, status: str | None, timeout_seconds: float) -> dict:
        deadline = time.monotonic() + timeout_seconds
        with self.condition:
            while time.monotonic() < deadline:
                for payload in self.payloads:
                    if payload.get("externalTaskId") != external_task_id:
                        continue
                    if status is None or payload.get("status") == status:
                        return payload
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    self.condition.wait(min(remaining, 1.0))
        if status is None:
            raise RuntimeError(f"no callback received for externalTaskId={external_task_id!r}")
        raise RuntimeError(f"no {status} callback received for externalTaskId={external_task_id!r}")


def make_handler(state: CallbackState):
    class CallbackHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - http.server callback name
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as exc:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(str(exc).encode("utf-8"))
                return
            state.append(payload)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, format: str, *args: object) -> None:
            return

    return CallbackHandler


def get_json(base_url: str, path: str, request_id: str) -> dict:
    request = Request(
        base_url.rstrip("/") + path,
        headers={"Accept": "application/json", "X-Request-Id": request_id},
    )
    with urlopen(request, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError(f"{path} returned HTTP {response.status}")
        return json.loads(response.read().decode("utf-8"))


def post_json(base_url: str, path: str, payload: dict, request_id: str) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        base_url.rstrip("/") + path,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Request-Id": request_id,
        },
    )
    with urlopen(request, timeout=10) as response:
        if response.status not in {200, 202}:
            raise RuntimeError(f"{path} returned HTTP {response.status}")
        return json.loads(response.read().decode("utf-8"))


def refresh_until_terminalish(base_url: str, run_id: str, timeout_seconds: float) -> dict:
    deadline = time.monotonic() + timeout_seconds
    last_run: dict | None = None
    while time.monotonic() < deadline:
        try:
            last_run = post_json(base_url, f"/api/runs/{run_id}/refresh", {}, "compose-generic-refresh")
            if last_run.get("status") in {"NEEDS_REVIEW", "SUCCEEDED", "FAILED", "CANCELLED"}:
                return last_run
        except (HTTPError, URLError, TimeoutError, RuntimeError, OSError):
            pass
        time.sleep(2)
    if last_run is not None:
        return last_run
    return get_json(base_url, f"/api/runs/{run_id}", "compose-generic-get")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--callback-host", default="0.0.0.0")
    parser.add_argument("--callback-port", type=int, default=9109)
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    args = parser.parse_args()

    health = get_json(args.base_url, "/api/health", "compose-generic-health")
    if health.get("status") != "ok":
        raise RuntimeError(f"deployment is not healthy: {health}")
    if not health.get("callbacksEnabled"):
        raise RuntimeError("callbacks are disabled; start Compose with CODEAGENTX_CALLBACKS_ENABLED=true")

    state = CallbackState()
    server = ThreadingHTTPServer((args.callback_host, args.callback_port), make_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    suffix = uuid.uuid4().hex[:10]
    external_task_id = f"compose-generic-{suffix}"
    callback_url = f"http://host.docker.internal:{args.callback_port}/callback"
    payload = {
        "title": "Compose generic adapter callback smoke",
        "body": "Validate external task intake, mock runtime execution, and result callback delivery.",
        "idempotencyKey": external_task_id,
        "externalTaskId": external_task_id,
        "resultCallbackUrl": callback_url,
        "repositoryFullName": "local/compose-smoke",
        "baseBranch": "main",
        "provider": "mock",
        "model": "mock-model",
        "maxTurns": 1,
        "maxRunSeconds": 15.0,
        "permissionMode": "auto",
    }

    try:
        accepted = post_json(args.base_url, "/api/adapters/generic/tasks", payload, "compose-generic-submit")
        run_id = accepted["runId"]
        first_callback = state.wait_for_payload(external_task_id, args.timeout_seconds)
        final_run = refresh_until_terminalish(args.base_url, run_id, args.timeout_seconds)
        final_status = final_run.get("status")
        final_callback = state.wait_for_status(external_task_id, final_status, args.timeout_seconds)
        deliveries = get_json(args.base_url, f"/api/runs/{run_id}/callback-deliveries", "compose-generic-deliveries")
        audit = get_json(args.base_url, f"/api/runs/{run_id}/audit", "compose-generic-audit")
        if not any(item.get("status") == "DELIVERED" and item.get("event") == final_status for item in deliveries):
            raise RuntimeError(f"callback delivery record missing final status {final_status}: {deliveries}")
        if not audit.get("summary", {}).get("hasCallback"):
            raise RuntimeError(f"audit summary does not include callback evidence: {audit}")
        print(json.dumps({
            "accepted": {
                "taskId": accepted.get("taskId"),
                "runId": run_id,
                "status": accepted.get("status"),
            },
            "firstCallback": first_callback,
            "finalCallback": final_callback,
            "deliveryRecords": deliveries,
            "auditSummary": audit.get("summary"),
            "finalRun": {
                "runId": final_run.get("runId"),
                "status": final_run.get("status"),
                "runtimeRunId": final_run.get("runtimeRunId"),
            },
        }, indent=2, sort_keys=True))
        return 0
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())