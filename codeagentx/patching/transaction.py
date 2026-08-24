"""Patch transaction primitives for reliable file edits."""

from __future__ import annotations

import difflib
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4


MAX_RECORDED_DIFF_CHARS = 12_000


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PatchOperation(Enum):
    WRITE = "write_file"
    EDIT = "edit_file"


class PatchApplyError(Exception):
    """Raised when a patch transaction cannot be applied."""


@dataclass(frozen=True)
class PatchApplyResult:
    transaction_id: str
    operation: PatchOperation
    path: str
    before_exists: bool
    backup_path: str = ""
    diff: str = ""
    diff_truncated: bool = False
    bytes_before: int = 0
    bytes_after: int = 0
    applied_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PatchApplyResult":
        return cls(
            transaction_id=str(payload["transaction_id"]),
            operation=PatchOperation(str(payload["operation"])),
            path=str(payload["path"]),
            before_exists=bool(payload.get("before_exists", False)),
            backup_path=str(payload.get("backup_path", "")),
            diff=str(payload.get("diff", "")),
            diff_truncated=bool(payload.get("diff_truncated", False)),
            bytes_before=int(payload.get("bytes_before", 0) or 0),
            bytes_after=int(payload.get("bytes_after", 0) or 0),
            applied_at=str(payload.get("applied_at", utc_now_iso())),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "operation": self.operation.value,
            "path": self.path,
            "before_exists": self.before_exists,
            "backup_path": self.backup_path,
            "diff": self.diff,
            "diff_truncated": self.diff_truncated,
            "bytes_before": self.bytes_before,
            "bytes_after": self.bytes_after,
            "applied_at": self.applied_at,
        }


@dataclass(frozen=True)
class PatchRollbackResult:
    transaction_id: str
    path: str
    restored: bool
    message: str
    rolled_back_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "path": self.path,
            "restored": self.restored,
            "message": self.message,
            "rolled_back_at": self.rolled_back_at,
        }


class PatchTransaction:
    """Applies one file change with a unified diff and rollback artifact."""

    def __init__(
        self,
        *,
        path: str | Path,
        operation: PatchOperation,
        before_content: str,
        after_content: str,
        before_exists: bool,
        transaction_id: str | None = None,
    ) -> None:
        self.path = Path(path).expanduser()
        self.operation = operation
        self.before_content = before_content
        self.after_content = after_content
        self.before_exists = before_exists
        self.transaction_id = transaction_id or str(uuid4())

    @classmethod
    def for_write(cls, path: str | Path, content: str) -> "PatchTransaction":
        filepath = Path(path).expanduser()
        before_exists = filepath.exists()
        before_content = ""
        if before_exists:
            before_content = filepath.read_text(
                encoding="utf-8",
                errors="replace",
            )
        return cls(
            path=filepath,
            operation=PatchOperation.WRITE,
            before_content=before_content,
            after_content=content,
            before_exists=before_exists,
        )

    @classmethod
    def for_edit(
        cls,
        path: str | Path,
        *,
        before_content: str,
        after_content: str,
    ) -> "PatchTransaction":
        return cls(
            path=path,
            operation=PatchOperation.EDIT,
            before_content=before_content,
            after_content=after_content,
            before_exists=True,
        )

    def preview_diff(self) -> str:
        before_name = str(self.path) if self.before_exists else "/dev/null"
        after_name = str(self.path)
        return "".join(difflib.unified_diff(
            self.before_content.splitlines(keepends=True),
            self.after_content.splitlines(keepends=True),
            fromfile=before_name,
            tofile=after_name,
            lineterm="\n",
        ))

    def apply(self, backup_root: str | Path | None = None) -> PatchApplyResult:
        backup_path = ""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.before_exists:
                backup = self._backup_path(backup_root)
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_text(self.before_content, encoding="utf-8")
                backup_path = str(backup)

            tmp_path = self.path.with_name(f".{self.path.name}.{self.transaction_id}.tmp")
            tmp_path.write_text(self.after_content, encoding="utf-8")
            try:
                tmp_path.replace(self.path)
            except PermissionError:
                self.path.write_text(self.after_content, encoding="utf-8")
                tmp_path.unlink(missing_ok=True)
        except Exception as exc:
            self._best_effort_rollback(backup_path)
            raise PatchApplyError(
                f"failed to apply patch transaction {self.transaction_id}: {exc}"
            ) from exc

        diff, truncated = truncate_diff(self.preview_diff())
        return PatchApplyResult(
            transaction_id=self.transaction_id,
            operation=self.operation,
            path=str(self.path),
            before_exists=self.before_exists,
            backup_path=backup_path,
            diff=diff,
            diff_truncated=truncated,
            bytes_before=len(self.before_content.encode("utf-8")),
            bytes_after=len(self.after_content.encode("utf-8")),
        )

    def rollback(self, result: PatchApplyResult) -> PatchRollbackResult:
        if result.backup_path:
            backup_path = Path(result.backup_path)
            if not backup_path.exists():
                return PatchRollbackResult(
                    transaction_id=result.transaction_id,
                    path=result.path,
                    restored=False,
                    message=f"backup not found: {backup_path}",
                )
            self.path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(backup_path, self.path)
            return PatchRollbackResult(
                transaction_id=result.transaction_id,
                path=result.path,
                restored=True,
                message=f"restored from backup: {backup_path}",
            )

        if not result.before_exists:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            return PatchRollbackResult(
                transaction_id=result.transaction_id,
                path=result.path,
                restored=True,
                message="removed file created by transaction",
            )

        return PatchRollbackResult(
            transaction_id=result.transaction_id,
            path=result.path,
            restored=False,
            message="transaction has no rollback artifact",
        )

    @classmethod
    def rollback_applied(cls, result: PatchApplyResult) -> PatchRollbackResult:
        transaction = cls(
            path=result.path,
            operation=result.operation,
            before_content="",
            after_content="",
            before_exists=result.before_exists,
            transaction_id=result.transaction_id,
        )
        return transaction.rollback(result)

    def _backup_path(self, backup_root: str | Path | None) -> Path:
        if backup_root is None:
            backup_root = self.path.parent / ".patch_backups"
        root = Path(backup_root).expanduser()
        suffix = self.path.suffix or ".txt"
        return root / f"{self.path.name}.{self.transaction_id}{suffix}.bak"

    def _best_effort_rollback(self, backup_path: str) -> None:
        if not backup_path:
            return
        backup = Path(backup_path)
        if backup.exists():
            shutil.copyfile(backup, self.path)


def truncate_diff(diff: str, max_chars: int = MAX_RECORDED_DIFF_CHARS) -> tuple[str, bool]:
    if len(diff) <= max_chars:
        return diff, False
    omitted = len(diff) - max_chars
    return diff[:max_chars] + f"\n... diff truncated {omitted} chars", True
