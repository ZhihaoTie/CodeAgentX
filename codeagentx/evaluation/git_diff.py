"""Git diff collection for benchmark and external evaluator reports."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Any
from uuid import uuid4


GIT_DIFF_ARTIFACT_SCHEMA_VERSION = "codeagentx.git_diff_artifact.v1"
DEFAULT_GIT_DIFF_IGNORED_PATHS = (
    ".codeagentx",
    ".codeagentx/*",
    ".pytest_cache",
    ".pytest_cache/*",
    "__pycache__",
    "*/__pycache__/*",
    "*.pyc",
    "*.pyo",
)


@dataclass(frozen=True)
class GitDiffReport:
    """A repository-level patch snapshot collected from git."""

    workspace_root: str
    base_ref: str = "HEAD"
    status_porcelain: str = ""
    patch_diff: str = ""
    changed_files: list[str] = field(default_factory=list)
    untracked_files: list[str] = field(default_factory=list)
    deleted_files: list[str] = field(default_factory=list)
    renamed_files: list[str] = field(default_factory=list)
    is_git_repository: bool = True
    error: str | None = None

    @property
    def patch_bytes(self) -> int:
        return len(self.patch_diff.encode("utf-8"))

    @property
    def is_clean(self) -> bool:
        return (
            self.is_git_repository
            and not self.changed_files
            and not self.untracked_files
            and not self.patch_diff
            and self.error is None
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_root": self.workspace_root,
            "base_ref": self.base_ref,
            "status_porcelain": self.status_porcelain,
            "patch_diff": self.patch_diff,
            "patch_bytes": self.patch_bytes,
            "changed_files": list(self.changed_files),
            "untracked_files": list(self.untracked_files),
            "deleted_files": list(self.deleted_files),
            "renamed_files": list(self.renamed_files),
            "is_git_repository": self.is_git_repository,
            "is_clean": self.is_clean,
            "error": self.error,
        }


def collect_git_diff(
    workspace_root: str | Path,
    *,
    base_ref: str = "HEAD",
    include_untracked: bool = True,
    ignored_paths: Iterable[str] | None = None,
    timeout_seconds: int = 30,
) -> GitDiffReport:
    """Collect a full-workspace git diff snapshot.

    The tracked patch is collected with `git diff --binary <base_ref>`. Text
    untracked files are appended as simple new-file patches so benchmark reports
    can account for files created outside CodeAgent-X's write/edit tools. Runtime
    metadata such as `.codeagentx/` is ignored by default to keep evaluator
    patches focused on repository code changes.
    """

    root = Path(workspace_root).resolve()
    if not root.exists():
        return GitDiffReport(
            workspace_root=str(root),
            base_ref=base_ref,
            is_git_repository=False,
            error=f"workspace does not exist: {root}",
        )

    try:
        repo_check = _run_git(
            ["rev-parse", "--show-toplevel"],
            cwd=root,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return GitDiffReport(
            workspace_root=str(root),
            base_ref=base_ref,
            is_git_repository=False,
            error=f"git diff collection failed: {exc.__class__.__name__}: {exc}",
        )
    if repo_check.returncode != 0:
        return GitDiffReport(
            workspace_root=str(root),
            base_ref=base_ref,
            is_git_repository=False,
            error=_command_error(repo_check),
        )

    try:
        status_result = _run_git(
            ["status", "--porcelain=v1"],
            cwd=root,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return GitDiffReport(
            workspace_root=str(root),
            base_ref=base_ref,
            is_git_repository=True,
            error=f"git status collection failed: {exc.__class__.__name__}: {exc}",
        )
    if status_result.returncode != 0:
        return GitDiffReport(
            workspace_root=str(root),
            base_ref=base_ref,
            is_git_repository=True,
            error=_command_error(status_result),
        )

    try:
        diff_result = _run_git(
            ["diff", "--binary", base_ref],
            cwd=root,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return GitDiffReport(
            workspace_root=str(root),
            base_ref=base_ref,
            status_porcelain=status_result.stdout,
            is_git_repository=True,
            error=f"git diff collection failed: {exc.__class__.__name__}: {exc}",
        )
    if diff_result.returncode != 0:
        return GitDiffReport(
            workspace_root=str(root),
            base_ref=base_ref,
            status_porcelain=status_result.stdout,
            is_git_repository=True,
            error=_command_error(diff_result),
        )

    ignore_patterns = tuple(
        DEFAULT_GIT_DIFF_IGNORED_PATHS
        if ignored_paths is None
        else ignored_paths
    )
    parsed = _filter_ignored_paths(
        _parse_porcelain_status(status_result.stdout),
        ignore_patterns,
    )
    patch_diff = diff_result.stdout
    if include_untracked:
        patch_diff += _untracked_patches(root, parsed["untracked_files"])

    return GitDiffReport(
        workspace_root=str(root),
        base_ref=base_ref,
        status_porcelain=status_result.stdout,
        patch_diff=patch_diff,
        changed_files=parsed["changed_files"],
        untracked_files=parsed["untracked_files"],
        deleted_files=parsed["deleted_files"],
        renamed_files=parsed["renamed_files"],
        is_git_repository=True,
    )


def write_git_diff_artifacts(
    report: GitDiffReport,
    artifact_root: str | Path,
    *,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Persist a collected git diff as report-friendly benchmark artifacts."""

    artifact_id = f"git-diff-{uuid4().hex[:12]}"
    root = Path(artifact_root).expanduser()
    if task_id:
        root = root / _safe_slug(task_id)
    artifact_dir = root / artifact_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    patch_path = artifact_dir / "patch.diff"
    result_path = artifact_dir / "git_diff.json"
    manifest_path = artifact_dir / "manifest.json"

    payload = {
        "schema_version": GIT_DIFF_ARTIFACT_SCHEMA_VERSION,
        **report.to_dict(),
    }
    patch_path.write_text(report.patch_diff, encoding="utf-8")
    result_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    manifest = {
        "schema_version": GIT_DIFF_ARTIFACT_SCHEMA_VERSION,
        "artifact_id": artifact_id,
        "kind": "git_diff",
        "task_id": task_id,
        "created_at": _utc_now_iso(),
        "artifact_dir": str(artifact_dir),
        "patch_path": str(patch_path),
        "result_path": str(result_path),
        "manifest_path": str(manifest_path),
        "workspace_root": report.workspace_root,
        "base_ref": report.base_ref,
        "patch_bytes": report.patch_bytes,
        "changed_files": list(report.changed_files),
        "untracked_files": list(report.untracked_files),
        "deleted_files": list(report.deleted_files),
        "renamed_files": list(report.renamed_files),
        "is_git_repository": report.is_git_repository,
        "is_clean": report.is_clean,
        "error": report.error,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def _run_git(args: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )


def _parse_porcelain_status(output: str) -> dict[str, list[str]]:
    changed_files: list[str] = []
    untracked_files: list[str] = []
    deleted_files: list[str] = []
    renamed_files: list[str] = []

    for raw_line in output.splitlines():
        if not raw_line:
            continue
        if raw_line.startswith("?? "):
            path = _normalize_status_path(raw_line[3:])
            untracked_files.append(path)
            changed_files.append(path)
            continue

        status = raw_line[:2]
        path = raw_line[3:]
        if " -> " in path and ("R" in status or "C" in status):
            old_path, new_path = path.split(" -> ", 1)
            path = new_path
            renamed_files.append(
                f"{_normalize_status_path(old_path)} -> {_normalize_status_path(new_path)}"
            )
        normalized = _normalize_status_path(path)
        changed_files.append(normalized)
        if "D" in status:
            deleted_files.append(normalized)

    return {
        "changed_files": _unique(changed_files),
        "untracked_files": _unique(untracked_files),
        "deleted_files": _unique(deleted_files),
        "renamed_files": _unique(renamed_files),
    }


def _filter_ignored_paths(
    parsed: dict[str, list[str]],
    ignored_paths: tuple[str, ...],
) -> dict[str, list[str]]:
    if not ignored_paths:
        return parsed
    return {
        key: [
            path
            for path in values
            if not _matches_ignored_path(path, ignored_paths)
        ]
        for key, values in parsed.items()
    }


def _matches_ignored_path(path: str, ignored_paths: tuple[str, ...]) -> bool:
    candidates = [item.strip().rstrip("/") for item in path.split(" -> ")]
    return any(
        fnmatch(candidate, pattern.rstrip("/"))
        for candidate in candidates
        for pattern in ignored_paths
    )


def _untracked_patches(root: Path, untracked_files: list[str]) -> str:
    chunks: list[str] = []
    for relative in untracked_files:
        path = root / relative
        if not path.is_file():
            continue
        chunks.append(_untracked_file_patch(path, relative))
    if not chunks:
        return ""
    return "\n" + "\n".join(chunks)


def _untracked_file_patch(path: Path, relative_path: str) -> str:
    data = path.read_bytes()
    display_path = relative_path.replace("\\", "/")
    if b"\0" in data:
        return (
            f"diff --git a/{display_path} b/{display_path}\n"
            "new file mode 100644\n"
            f"Binary files /dev/null and b/{display_path} differ\n"
        )

    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    patch_lines = [
        f"diff --git a/{display_path} b/{display_path}\n",
        "new file mode 100644\n",
        "--- /dev/null\n",
        f"+++ b/{display_path}\n",
        f"@@ -0,0 +1,{len(lines)} @@\n",
    ]
    patch_lines.extend(f"+{line}" for line in lines)
    if text and not text.endswith("\n"):
        patch_lines.append("\\ No newline at end of file\n")
    return "".join(patch_lines)


def _normalize_status_path(path: str) -> str:
    return path.strip().strip('"').replace("\\", "/")


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _command_error(result: subprocess.CompletedProcess[str]) -> str:
    stderr = result.stderr.strip()
    stdout = result.stdout.strip()
    detail = stderr or stdout or "unknown git error"
    return f"git {' '.join(result.args[1:])} failed with exit code {result.returncode}: {detail}"


def _safe_slug(value: str) -> str:
    chars = [
        char if char.isalnum() or char in ("-", "_", ".") else "-"
        for char in str(value).strip()
    ]
    slug = "".join(chars).strip("-._")
    return slug or "artifact"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
