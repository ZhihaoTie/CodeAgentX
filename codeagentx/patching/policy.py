"""Patch policy checks for agent-generated file changes."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePath
from typing import Any, Iterable, Mapping

from .transaction import utc_now_iso


class PatchPolicyStatus(Enum):
    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"
    SKIPPED = "skipped"


class PatchPolicySeverity(Enum):
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass(frozen=True)
class PatchPolicyViolation:
    rule: str
    severity: PatchPolicySeverity
    message: str
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "severity": self.severity.value,
            "message": self.message,
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True)
class PatchPolicyReport:
    status: PatchPolicyStatus
    summary: str
    changed_files: int = 0
    patch_count: int = 0
    added_lines: int = 0
    deleted_lines: int = 0
    total_changed_lines: int = 0
    total_bytes_delta: int = 0
    diff_truncated_count: int = 0
    violations: list[PatchPolicyViolation] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)

    @property
    def failed(self) -> bool:
        return self.status == PatchPolicyStatus.FAILED

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "summary": self.summary,
            "changed_files": self.changed_files,
            "patch_count": self.patch_count,
            "added_lines": self.added_lines,
            "deleted_lines": self.deleted_lines,
            "total_changed_lines": self.total_changed_lines,
            "total_bytes_delta": self.total_bytes_delta,
            "diff_truncated_count": self.diff_truncated_count,
            "violations": [violation.to_dict() for violation in self.violations],
            "created_at": self.created_at,
        }


class PatchPolicy:
    """Evaluate patch metadata against configurable quality limits."""

    def __init__(
        self,
        *,
        forbidden_paths: Iterable[str] | None = None,
        max_changed_files: int = 20,
        max_total_changed_lines: int = 1_200,
        max_single_file_bytes_delta: int = 1_000_000,
        fail_on_empty_patch: bool = True,
    ) -> None:
        self.forbidden_paths = list(forbidden_paths or [])
        self.max_changed_files = max_changed_files
        self.max_total_changed_lines = max_total_changed_lines
        self.max_single_file_bytes_delta = max_single_file_bytes_delta
        self.fail_on_empty_patch = fail_on_empty_patch

    @classmethod
    def from_config(cls, config: Any) -> "PatchPolicy":
        return cls(
            forbidden_paths=getattr(config, "patch_policy_forbidden_paths", []),
            max_changed_files=getattr(config, "patch_policy_max_changed_files", 20),
            max_total_changed_lines=getattr(config, "patch_policy_max_total_changed_lines", 1_200),
            max_single_file_bytes_delta=getattr(
                config,
                "patch_policy_max_single_file_bytes_delta",
                1_000_000,
            ),
            fail_on_empty_patch=getattr(config, "patch_policy_fail_on_empty_patch", True),
        )

    def evaluate(self, patches: Iterable[Mapping[str, Any]]) -> PatchPolicyReport:
        patch_payloads = [dict(patch) for patch in patches]
        if not patch_payloads:
            return PatchPolicyReport(
                status=PatchPolicyStatus.SKIPPED,
                summary="No patch metadata recorded.",
            )

        changed_paths = {
            _normalize_path(patch.get("path", ""))
            for patch in patch_payloads
            if patch.get("path")
        }
        added_lines = 0
        deleted_lines = 0
        total_bytes_delta = 0
        diff_truncated_count = 0
        violations: list[PatchPolicyViolation] = []

        for patch in patch_payloads:
            path = _normalize_path(patch.get("path", ""))
            diff_stats = _diff_stats(str(patch.get("diff", "") or ""))
            added_lines += diff_stats["added"]
            deleted_lines += diff_stats["deleted"]
            bytes_before = int(patch.get("bytes_before", 0) or 0)
            bytes_after = int(patch.get("bytes_after", 0) or 0)
            byte_delta = bytes_after - bytes_before
            total_bytes_delta += byte_delta

            if _is_forbidden(path, self.forbidden_paths):
                violations.append(PatchPolicyViolation(
                    rule="forbidden_path",
                    severity=PatchPolicySeverity.CRITICAL,
                    message=f"Patch modifies forbidden path: {path}",
                    evidence={"path": path, "patterns": list(self.forbidden_paths)},
                ))

            if self.fail_on_empty_patch and _is_empty_patch(patch):
                violations.append(PatchPolicyViolation(
                    rule="empty_patch",
                    severity=PatchPolicySeverity.ERROR,
                    message=f"Patch transaction made no content changes: {path}",
                    evidence={
                        "path": path,
                        "transaction_id": patch.get("transaction_id"),
                        "operation": patch.get("operation"),
                    },
                ))

            if abs(byte_delta) > self.max_single_file_bytes_delta:
                violations.append(PatchPolicyViolation(
                    rule="single_file_size_delta",
                    severity=PatchPolicySeverity.ERROR,
                    message=f"Patch changes {abs(byte_delta)} bytes in one file: {path}",
                    evidence={
                        "path": path,
                        "bytes_before": bytes_before,
                        "bytes_after": bytes_after,
                        "limit": self.max_single_file_bytes_delta,
                    },
                ))

            if bool(patch.get("diff_truncated", False)):
                diff_truncated_count += 1
                violations.append(PatchPolicyViolation(
                    rule="diff_truncated",
                    severity=PatchPolicySeverity.WARNING,
                    message=f"Patch diff was truncated for: {path}",
                    evidence={"path": path, "transaction_id": patch.get("transaction_id")},
                ))

        total_changed_lines = added_lines + deleted_lines
        if len(changed_paths) > self.max_changed_files:
            violations.append(PatchPolicyViolation(
                rule="changed_file_limit",
                severity=PatchPolicySeverity.ERROR,
                message=f"Patch touches {len(changed_paths)} files; limit is {self.max_changed_files}.",
                evidence={
                    "changed_files": len(changed_paths),
                    "limit": self.max_changed_files,
                    "paths": sorted(changed_paths),
                },
            ))

        if total_changed_lines > self.max_total_changed_lines:
            violations.append(PatchPolicyViolation(
                rule="changed_line_limit",
                severity=PatchPolicySeverity.ERROR,
                message=(
                    f"Patch changes {total_changed_lines} diff lines; "
                    f"limit is {self.max_total_changed_lines}."
                ),
                evidence={
                    "total_changed_lines": total_changed_lines,
                    "limit": self.max_total_changed_lines,
                },
            ))

        status = _status_for(violations)
        return PatchPolicyReport(
            status=status,
            summary=_summary_for(status, len(patch_payloads), len(changed_paths), violations),
            changed_files=len(changed_paths),
            patch_count=len(patch_payloads),
            added_lines=added_lines,
            deleted_lines=deleted_lines,
            total_changed_lines=total_changed_lines,
            total_bytes_delta=total_bytes_delta,
            diff_truncated_count=diff_truncated_count,
            violations=violations,
        )


def _normalize_path(value: Any) -> str:
    path = str(value or "").replace("\\", "/")
    if not path:
        return ""
    return PurePath(path).as_posix()


def _is_forbidden(path: str, patterns: Iterable[str]) -> bool:
    normalized = _strip_relative_prefix(path)
    name = PurePath(normalized).name
    for pattern in patterns:
        normalized_pattern = _strip_relative_prefix(str(pattern).replace("\\", "/"))
        if fnmatch.fnmatch(normalized, normalized_pattern):
            return True
        if fnmatch.fnmatch(normalized, f"*/{normalized_pattern}"):
            return True
        if fnmatch.fnmatch(name, normalized_pattern):
            return True
    return False


def _strip_relative_prefix(value: str) -> str:
    result = value
    while result.startswith("./"):
        result = result[2:]
    return result


def _is_empty_patch(patch: Mapping[str, Any]) -> bool:
    diff = str(patch.get("diff", "") or "").strip()
    bytes_before = int(patch.get("bytes_before", 0) or 0)
    bytes_after = int(patch.get("bytes_after", 0) or 0)
    return not diff and bytes_before == bytes_after


def _diff_stats(diff: str) -> dict[str, int]:
    added = 0
    deleted = 0
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            deleted += 1
    return {"added": added, "deleted": deleted}


def _status_for(violations: list[PatchPolicyViolation]) -> PatchPolicyStatus:
    if any(
        violation.severity in (PatchPolicySeverity.ERROR, PatchPolicySeverity.CRITICAL)
        for violation in violations
    ):
        return PatchPolicyStatus.FAILED
    if violations:
        return PatchPolicyStatus.WARNING
    return PatchPolicyStatus.PASSED


def _summary_for(
    status: PatchPolicyStatus,
    patch_count: int,
    changed_files: int,
    violations: list[PatchPolicyViolation],
) -> str:
    if status == PatchPolicyStatus.PASSED:
        return f"Patch policy passed for {patch_count} patch(es) across {changed_files} file(s)."
    if status == PatchPolicyStatus.WARNING:
        return f"Patch policy completed with {len(violations)} warning(s)."
    if status == PatchPolicyStatus.FAILED:
        return f"Patch policy failed with {len(violations)} violation(s)."
    return "Patch policy skipped."
