"""Rollback helpers for applied patch metadata."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .transaction import PatchApplyResult, PatchRollbackResult, PatchTransaction, utc_now_iso


@dataclass(frozen=True)
class PatchRollbackReport:
    """Summary of rollback attempts for a failed agent run."""

    attempted: int
    restored: int
    failed: int
    results: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)

    @property
    def status(self) -> str:
        if self.attempted == 0:
            return "skipped"
        if self.failed == 0:
            return "passed"
        if self.restored > 0:
            return "partial"
        return "failed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "attempted": self.attempted,
            "restored": self.restored,
            "failed": self.failed,
            "results": list(self.results),
            "created_at": self.created_at,
        }


def rollback_applied_patches(
    patches: Iterable[Mapping[str, Any]],
) -> PatchRollbackReport:
    """Rollback applied patches in reverse order.

    The input is the `ToolResult.metadata["patch"]` payload recorded in the
    trajectory. Reversing preserves correctness when a run edits the same file
    multiple times.
    """

    patch_payloads = [dict(patch) for patch in patches]
    rollback_results: list[dict[str, Any]] = []

    for patch in reversed(patch_payloads):
        try:
            apply_result = PatchApplyResult.from_dict(patch)
            rollback_result = PatchTransaction.rollback_applied(apply_result)
            rollback_results.append(rollback_result.to_dict())
        except Exception as exc:
            rollback_results.append(_rollback_error(patch, exc))

    restored = sum(1 for result in rollback_results if result.get("restored") is True)
    failed = len(rollback_results) - restored
    return PatchRollbackReport(
        attempted=len(rollback_results),
        restored=restored,
        failed=failed,
        results=rollback_results,
    )


def _rollback_error(patch: Mapping[str, Any], exc: Exception) -> dict[str, Any]:
    return PatchRollbackResult(
        transaction_id=str(patch.get("transaction_id", "")),
        path=str(patch.get("path", "")),
        restored=False,
        message=f"rollback failed: {exc.__class__.__name__}: {exc}",
    ).to_dict()
