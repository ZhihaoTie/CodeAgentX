"""Verify duplicate GitHub workflow_run webhooks are idempotent.

This smoke proves a V2 reliability property:

    duplicate CI webhook -> no duplicate final-text pollution

Start the Python runtime and the control plane with the smoke profile, then run
this script from the project root.
"""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.request import Request, urlopen
from uuid import uuid4


CONTROL_PLANE_URL = "http://127.0.0.1:8080"


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    request = Request(url, data=data, headers=request_headers, method="POST")
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def get_json(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_status(run_id: str, statuses: set[str], timeout_seconds: float = 60.0) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last: dict[str, Any] | None = None
    while time.time() < deadline:
        last = get_json(f"{CONTROL_PLANE_URL}/api/runs/{run_id}")
        print(f"run {run_id}: {last.get('status')}")
        if last.get("status") in statuses:
            return last
        time.sleep(0.5)
    raise RuntimeError(f"timed out waiting for {statuses}; last={last}")


def main() -> int:
    health = get_json(f"{CONTROL_PLANE_URL}/api/health")
    print("health:", json.dumps(health, ensure_ascii=False))

    created = post_json(
        f"{CONTROL_PLANE_URL}/api/tasks",
        {
            "source": "duplicate-workflow-run-smoke",
            "title": "Duplicate workflow_run idempotency smoke",
            "body": "Create a reviewable run, authorize the noop PR, then replay CI webhooks.",
            "idempotencyKey": "duplicate-workflow-run-smoke-" + uuid4().hex[:8],
        },
    )
    run_id = created["runId"]
    print("created run:", run_id)
    run = wait_for_status(run_id, {"NEEDS_REVIEW", "FAILED", "CANCELLED"})
    if run.get("status") != "NEEDS_REVIEW":
        raise RuntimeError(f"expected NEEDS_REVIEW before authorization, got: {run}")

    authorized = post_json(
        f"{CONTROL_PLANE_URL}/api/runs/{run_id}/review",
        {
            "decision": "AUTHORIZE_PR",
            "comment": "Authorize noop PR publication for duplicate CI webhook smoke.",
        },
    )
    print("authorized:", authorized.get("status"), authorized.get("patchBranch"))
    if authorized.get("status") != "PR_CREATED":
        raise RuntimeError(f"expected PR_CREATED, got: {authorized}")

    payload = {
        "action": "completed",
        "workflow_run": {
            "head_branch": authorized["patchBranch"],
            "status": "completed",
            "conclusion": "success",
            "html_url": "https://github.com/acme/repo/actions/runs/duplicate-smoke",
        },
    }
    headers = {
        "X-GitHub-Event": "workflow_run",
        "X-GitHub-Delivery": "duplicate-ci-delivery",
    }
    first = post_json(f"{CONTROL_PLANE_URL}/api/webhooks/github", payload, headers)
    second = post_json(f"{CONTROL_PLANE_URL}/api/webhooks/github", payload, headers)
    print("first:", first.get("status"), first.get("finalText"))
    print("second:", second.get("status"), second.get("finalText"))

    if second.get("status") != "SUCCEEDED":
        raise RuntimeError(f"expected SUCCEEDED, got: {second}")
    final_text = str(second.get("finalText") or "")
    if final_text.count("CI succeeded:") != 1:
        raise RuntimeError(f"expected one CI succeeded line, got: {final_text!r}")
    print("duplicate workflow_run smoke succeeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())