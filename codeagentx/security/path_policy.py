"""Workspace path policy for tool execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PathPolicyResult:
    allowed: bool
    path: Path | None = None
    reason: str = ""


class WorkspacePathPolicy:
    """Restricts filesystem tool paths to a configured workspace root."""

    def __init__(self, workspace_root: str | Path, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self.root = Path(workspace_root).expanduser().resolve()

    def check_path(self, raw_path: str | Path, *, must_be_dir: bool = False) -> PathPolicyResult:
        if not self.enabled:
            return PathPolicyResult(allowed=True, path=Path(raw_path).expanduser())

        if raw_path is None or str(raw_path).strip() == "":
            return PathPolicyResult(allowed=False, reason="path must not be empty")

        candidate = self._resolve(raw_path)
        if not _is_relative_to(candidate, self.root):
            return PathPolicyResult(
                allowed=False,
                path=candidate,
                reason=f"path is outside workspace: {candidate}",
            )

        if must_be_dir and candidate.exists() and not candidate.is_dir():
            return PathPolicyResult(
                allowed=False,
                path=candidate,
                reason=f"path is not a directory: {candidate}",
            )

        return PathPolicyResult(allowed=True, path=candidate)

    def _resolve(self, raw_path: str | Path) -> Path:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = self.root / path
        return path.resolve(strict=False)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
