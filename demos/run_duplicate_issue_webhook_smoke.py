"""Replay the same GitHub issue webhook and verify idempotency.

This smoke proves a V2 reliability property:

    same X-GitHub-Delivery replayed twice -> one Task / Run

Start dependencies separately:

    py -3.13 -B -m codeagentx.service --host 127.0.0.1 --port 8765

    cd control-plane
    mvn spring-boot:run "-Dspring-boot.run.profiles=smoke"
"""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen
from uuid import uuid4


CONTROL_PLANE_URL = "http://127.0.0.1:8080"
TARGET_REPOSITORY_URL = "https://github.com/ZhihaoTie/CodeAgent.git"
TARGET_REPOSITORY_FULL_NAME = "ZhihaoTie/CodeAgent"
TARGET_BASE_BRANCH = "main"


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def get_json(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_status(run_id: str, terminal: set[str], timeout_seconds: float = 180.0) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last: dict[str, Any] | None = None
    while time.time() < deadline:
        last = get_json(f"{CONTROL_PLANE_URL}/api/runs/{run_id}")
        print(f"run {run_id}: {last.get('status')}")
        if last.get("status") in terminal:
            return last
        time.sleep(2)
    raise RuntimeError(f"timed out waiting for {sorted(terminal)}; last={last}")


def build_issue_payload() -> dict[str, Any]:
    return {
        "action": "opened",
        "issue": {
            "number": 1,
            "title": "Fix normalize_title casing behavior",
            "body": (
                "The normalize_title function should trim surrounding spaces and "
                "convert words to title case. Current behavior returns lowercase "
                "text and fails tests/test_string_utils.py."
            ),
            "html_url": "https://github.com/ZhihaoTie/CodeAgent/issues/1",
        },
        "repository": {
            "full_name": TARGET_REPOSITORY_FULL_NAME,
            "clone_url": TARGET_REPOSITORY_URL,
            "html_url": "https://github.com/ZhihaoTie/CodeAgent",
            "default_branch": TARGET_BASE_BRANCH,
        },
    }


def main() -> int:
    delivery_id = "duplicate-issue-smoke-" + uuid4().hex[:8]
    headers = {
        "X-GitHub-Event": "issues",
        "X-GitHub-Delivery": delivery_id,
    }
    payload = build_issue_payload()

    try:
        health = get_json(f"{CONTROL_PLANE_URL}/api/health")
        print("health:", json.dumps(health, ensure_ascii=False))
        first = post_json(f"{CONTROL_PLANE_URL}/api/webhooks/github", payload, headers=headers)
        second = post_json(f"{CONTROL_PLANE_URL}/api/webhooks/github", payload, headers=headers)
    except URLError as exc:
        print("control plane is not reachable.")
        print('Start it with: cd control-plane; mvn spring-boot:run "-Dspring-boot.run.profiles=smoke"')
        raise SystemExit(2) from exc

    first_run_id = first.get("runId")
    second_run_id = second.get("runId")
    print("delivery id:", delivery_id)
    print("first run:", first_run_id)
    print("second run:", second_run_id)

    if not first_run_id or first_run_id != second_run_id:
        raise RuntimeError(f"duplicate delivery created different runs: first={first_run_id}, second={second_run_id}")

    final = wait_for_status(first_run_id, {"NEEDS_REVIEW", "FAILED", "CANCELLED"})
    print("final:", json.dumps(final, indent=2, ensure_ascii=False))
    return 0 if final.get("status") == "NEEDS_REVIEW" else 1


if __name__ == "__main__":
    raise SystemExit(main())