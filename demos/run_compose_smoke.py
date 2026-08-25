#!/usr/bin/env python3
"""Smoke-check a Docker Compose deployment of CodeAgent-X.

The script is intentionally read-only: it checks health, preflight, and metrics
from the public control-plane endpoint without creating tasks or touching GitHub.
"""

from __future__ import annotations

import argparse
import json
from urllib.request import Request, urlopen


def get_json(base_url: str, path: str, request_id: str) -> dict:
    request = Request(
        base_url.rstrip("/") + path,
        headers={"Accept": "application/json", "X-Request-Id": request_id},
    )
    with urlopen(request, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError(f"{path} returned HTTP {response.status}")
        echoed = response.headers.get("X-Request-Id")
        if echoed != request_id:
            raise RuntimeError(f"{path} did not echo X-Request-Id: {echoed!r}")
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    args = parser.parse_args()

    request_id = "compose-smoke"
    health = get_json(args.base_url, "/api/health", request_id)
    preflight = get_json(args.base_url, "/api/config/preflight", request_id)
    metrics = get_json(args.base_url, "/api/metrics", request_id)

    if health.get("status") != "ok":
        raise RuntimeError(f"health is not ok: {health}")
    if health.get("runtime") != "ok" or health.get("database") != "ok":
        raise RuntimeError(f"dependencies are not healthy: {health}")
    if preflight.get("status") not in {"ready", "needs_configuration"}:
        raise RuntimeError(f"unexpected preflight status: {preflight}")
    if "runs" not in metrics or "worker" not in metrics:
        raise RuntimeError(f"metrics missing expected sections: {metrics}")

    print(json.dumps({
        "health": health,
        "preflightStatus": preflight.get("status"),
        "missing": preflight.get("missing", []),
        "warnings": preflight.get("warnings", []),
        "metrics": {
            "runs": metrics.get("runs"),
            "worker": metrics.get("worker"),
            "runtime": metrics.get("runtime"),
            "publisher": metrics.get("publisher"),
            "callbacks": metrics.get("callbacks"),
        },
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
