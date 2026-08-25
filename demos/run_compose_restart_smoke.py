#!/usr/bin/env python3
"""Restart a CodeAgent-X Compose deployment and verify it comes back healthy.

This smoke is intentionally read-only with respect to CodeAgent-X business data:
it restarts containers, waits for the public control-plane health surface, and
then reuses run_compose_smoke.py for health/preflight/metrics checks.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError

from run_compose_smoke import get_json


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILES = ["-f", "docker-compose.yml", "-f", "docker-compose.local.yml"]


def compose(*args: str) -> None:
    subprocess.run(["docker", "compose", *COMPOSE_FILES, *args], cwd=ROOT, check=True)


def wait_until_healthy(base_url: str, timeout_seconds: float) -> dict:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            health = get_json(base_url, "/api/health", "compose-restart-smoke")
            if health.get("status") == "ok":
                return health
        except (RuntimeError, URLError, TimeoutError, ConnectionError, OSError) as exc:
            last_error = exc
        time.sleep(2)
    raise RuntimeError(f"deployment did not become healthy within {timeout_seconds:.0f}s; last_error={last_error}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--skip-restart", action="store_true", help="Only wait and verify the current deployment.")
    args = parser.parse_args()

    if not args.skip_restart:
        compose("restart")
    wait_until_healthy(args.base_url, args.timeout_seconds)
    smoke = ROOT / "demos" / "run_compose_smoke.py"
    subprocess.run([sys.executable, str(smoke), "--base-url", args.base_url], cwd=ROOT, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
