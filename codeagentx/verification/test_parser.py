"""Structured parsing for common Python test runner output."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TestFramework(Enum):
    UNITTEST = "unittest"
    PYTEST = "pytest"
    UNKNOWN = "unknown"


class TestRunStatus(Enum):
    PASSED = "passed"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class StructuredTestResult:
    framework: TestFramework
    status: TestRunStatus
    total: int | None = None
    passed: int | None = None
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    duration_seconds: float | None = None
    failure_names: list[str] = field(default_factory=list)

    @property
    def recognized(self) -> bool:
        return self.framework != TestFramework.UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        return {
            "framework": self.framework.value,
            "status": self.status.value,
            "recognized": self.recognized,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "skipped": self.skipped,
            "duration_seconds": self.duration_seconds,
            "failure_names": list(self.failure_names),
        }


def parse_test_output(stdout: str = "", stderr: str = "") -> StructuredTestResult:
    """Parse stdout/stderr from common test runners."""
    text = "\n".join(part for part in (stdout or "", stderr or "") if part)
    if not text.strip():
        return _unknown()

    pytest_result = _parse_pytest(text)
    if pytest_result.recognized:
        return pytest_result

    unittest_result = _parse_unittest(text)
    if unittest_result.recognized:
        return unittest_result

    return _unknown()


def _parse_unittest(text: str) -> StructuredTestResult:
    ran_match = re.search(r"\bRan\s+(\d+)\s+tests?\s+in\s+([0-9.]+)s", text)
    if not ran_match:
        return _unknown()

    total = int(ran_match.group(1))
    duration = float(ran_match.group(2))
    status = TestRunStatus.UNKNOWN
    failed = 0
    errors = 0
    skipped = 0

    ok_match = re.search(r"^\s*OK(?:\s+\(([^)]*)\))?\s*$", text, flags=re.MULTILINE)
    failed_match = re.search(r"^\s*FAILED\s+\(([^)]*)\)\s*$", text, flags=re.MULTILINE)

    if ok_match:
        status = TestRunStatus.PASSED
        skipped = _extract_count(ok_match.group(1) or "", "skipped")
    elif failed_match:
        status = TestRunStatus.FAILED
        summary = failed_match.group(1)
        failed = _extract_count(summary, "failures")
        errors = _extract_count(summary, "errors")
        skipped = _extract_count(summary, "skipped")

    passed = max(total - failed - errors - skipped, 0)
    return StructuredTestResult(
        framework=TestFramework.UNITTEST,
        status=status,
        total=total,
        passed=passed,
        failed=failed,
        errors=errors,
        skipped=skipped,
        duration_seconds=duration,
        failure_names=_parse_unittest_failure_names(text),
    )


def _parse_pytest(text: str) -> StructuredTestResult:
    summary_match = re.search(
        r"=+\s*(?P<summary>[^=\n]*(?:passed|failed|error|errors|skipped|xfailed|xpassed)[^=\n]*)\s+in\s+(?P<duration>[0-9.]+)s\s*=+",
        text,
        flags=re.IGNORECASE,
    )
    if not summary_match:
        no_tests = re.search(r"\bno tests ran in\s+([0-9.]+)s", text, flags=re.IGNORECASE)
        if no_tests:
            return StructuredTestResult(
                framework=TestFramework.PYTEST,
                status=TestRunStatus.PASSED,
                total=0,
                passed=0,
                duration_seconds=float(no_tests.group(1)),
            )
        return _unknown()

    summary = summary_match.group("summary")
    duration = float(summary_match.group("duration"))
    passed = _extract_count(summary, "passed")
    failed = _extract_count(summary, "failed")
    errors = _extract_count(summary, "error") + _extract_count(summary, "errors")
    skipped = _extract_count(summary, "skipped")

    total = passed + failed + errors + skipped
    status = TestRunStatus.PASSED if failed == 0 and errors == 0 else TestRunStatus.FAILED
    return StructuredTestResult(
        framework=TestFramework.PYTEST,
        status=status,
        total=total,
        passed=passed,
        failed=failed,
        errors=errors,
        skipped=skipped,
        duration_seconds=duration,
        failure_names=_parse_pytest_failure_names(text),
    )


def _parse_unittest_failure_names(text: str) -> list[str]:
    names: list[str] = []
    for match in re.finditer(r"^(FAIL|ERROR):\s+(.+)$", text, flags=re.MULTILINE):
        names.append(match.group(2).strip())
    return names


def _parse_pytest_failure_names(text: str) -> list[str]:
    names: list[str] = []
    for match in re.finditer(r"^FAILED\s+(.+)$", text, flags=re.MULTILINE):
        names.append(match.group(1).strip())
    return names


def _extract_count(summary: str, label: str) -> int:
    if not summary:
        return 0
    equals_match = re.search(rf"\b{re.escape(label)}\s*=\s*(\d+)\b", summary, flags=re.IGNORECASE)
    if equals_match:
        return int(equals_match.group(1))
    match = re.search(rf"\b(\d+)\s+{re.escape(label)}\b", summary, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    return 0


def _unknown() -> StructuredTestResult:
    return StructuredTestResult(
        framework=TestFramework.UNKNOWN,
        status=TestRunStatus.UNKNOWN,
    )
