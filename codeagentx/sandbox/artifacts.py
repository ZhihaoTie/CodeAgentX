"""Sandbox artifact and workspace snapshot helpers."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from .runner import SandboxCommandResult


SANDBOX_ARTIFACT_SCHEMA_VERSION = "codeagentx.sandbox_artifact.v1"
WORKSPACE_SNAPSHOT_SCHEMA_VERSION = "codeagentx.workspace_snapshot.v1"

DEFAULT_IGNORED_DIRS = {
    ".codeagentx",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "node_modules",
    "venv",
}


@dataclass(frozen=True)
class WorkspaceSnapshot:
    workspace_root: str
    sha256: str
    file_count: int
    fingerprinted_files: int
    total_bytes: int
    truncated: bool = False
    recorded_files: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    ignored_dirs: list[str] = field(default_factory=list)
    schema_version: str = WORKSPACE_SNAPSHOT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "workspace_root": self.workspace_root,
            "sha256": self.sha256,
            "file_count": self.file_count,
            "fingerprinted_files": self.fingerprinted_files,
            "total_bytes": self.total_bytes,
            "truncated": self.truncated,
            "recorded_files": [dict(item) for item in self.recorded_files],
            "errors": [dict(item) for item in self.errors],
            "ignored_dirs": list(self.ignored_dirs),
        }


def snapshot_workspace(
    workspace_root: str | Path,
    *,
    max_files: int = 2_000,
    max_recorded_files: int = 100,
    ignored_dirs: set[str] | None = None,
) -> WorkspaceSnapshot:
    """Build a deterministic lightweight fingerprint for a workspace."""

    root = Path(workspace_root).expanduser().resolve(strict=False)
    ignored = set(ignored_dirs or DEFAULT_IGNORED_DIRS)
    digest = sha256()
    recorded_files: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    file_count = 0
    fingerprinted_files = 0
    total_bytes = 0
    truncated = False

    for path in _iter_workspace_files(root, ignored):
        file_count += 1
        if fingerprinted_files >= max_files:
            truncated = True
            break

        rel_path = _posix(path.relative_to(root))
        try:
            stat = path.stat()
            file_hash = _hash_file(path)
        except OSError as exc:
            errors.append({
                "path": rel_path,
                "error_type": exc.__class__.__name__,
                "message": str(exc),
            })
            continue

        fingerprinted_files += 1
        total_bytes += stat.st_size
        digest.update(rel_path.encode("utf-8", errors="replace"))
        digest.update(b"\0")
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\0")

        if len(recorded_files) < max_recorded_files:
            recorded_files.append({
                "path": rel_path,
                "size": stat.st_size,
                "sha256": file_hash,
            })

    return WorkspaceSnapshot(
        workspace_root=str(root),
        sha256=digest.hexdigest(),
        file_count=file_count,
        fingerprinted_files=fingerprinted_files,
        total_bytes=total_bytes,
        truncated=truncated,
        recorded_files=recorded_files,
        errors=errors,
        ignored_dirs=sorted(ignored),
    )


def write_sandbox_artifacts(
    result: SandboxCommandResult,
    artifact_root: str | Path,
    *,
    kind: str,
    task_id: str | None = None,
    include_workspace_snapshot: bool = True,
    snapshot_max_files: int = 2_000,
    snapshot_max_recorded_files: int = 100,
) -> dict[str, Any]:
    """Persist stdout/stderr/result JSON and return a report-friendly manifest."""

    artifact_id = f"{_safe_slug(kind)}-{uuid4().hex[:12]}"
    root = Path(artifact_root).expanduser()
    if task_id:
        root = root / _safe_slug(task_id)
    artifact_dir = root / artifact_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    stdout_path = artifact_dir / "stdout.txt"
    stderr_path = artifact_dir / "stderr.txt"
    result_path = artifact_dir / "result.json"
    manifest_path = artifact_dir / "manifest.json"

    workspace_snapshot = (
        snapshot_workspace(
            result.workspace_root,
            max_files=snapshot_max_files,
            max_recorded_files=snapshot_max_recorded_files,
        ).to_dict()
        if include_workspace_snapshot
        else None
    )
    stdout_path.write_text(result.stdout, encoding="utf-8")
    stderr_path.write_text(result.stderr, encoding="utf-8")

    result_payload = {
        "schema_version": SANDBOX_ARTIFACT_SCHEMA_VERSION,
        "artifact_id": artifact_id,
        "kind": kind,
        "task_id": task_id,
        "created_at": _utc_now_iso(),
        "result": result.to_dict(),
        "workspace_snapshot": workspace_snapshot,
    }
    result_path.write_text(
        json.dumps(result_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    manifest = {
        "schema_version": SANDBOX_ARTIFACT_SCHEMA_VERSION,
        "artifact_id": artifact_id,
        "kind": kind,
        "task_id": task_id,
        "created_at": result_payload["created_at"],
        "artifact_dir": str(artifact_dir),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "result_path": str(result_path),
        "manifest_path": str(manifest_path),
        "workspace_snapshot": workspace_snapshot,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def _iter_workspace_files(root: Path, ignored_dirs: set[str]):
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            dirname
            for dirname in dirnames
            if dirname not in ignored_dirs
        )
        for filename in sorted(filenames):
            path = Path(current) / filename
            if path.is_symlink() or not path.is_file():
                continue
            yield path


def _hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_slug(value: str) -> str:
    chars = [
        char if char.isalnum() or char in ("-", "_", ".") else "-"
        for char in str(value).strip()
    ]
    slug = "".join(chars).strip("-._")
    return slug or "artifact"


def _posix(path: Path) -> str:
    return "/".join(path.parts)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
