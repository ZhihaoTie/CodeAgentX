"""Deterministic task constraint verification."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from codeagentx.agent.state import AgentState


@dataclass(frozen=True)
class TaskConstraintSpec:
    success_criteria: list[str] = field(default_factory=list)
    required_changed_paths: list[str] = field(default_factory=list)
    forbidden_changed_paths: list[str] = field(default_factory=list)
    required_final_response_substrings: list[str] = field(default_factory=list)
    forbidden_final_response_substrings: list[str] = field(default_factory=list)

    @classmethod
    def from_config(cls, config: Any) -> "TaskConstraintSpec":
        return cls(
            success_criteria=_string_list(getattr(config, "task_success_criteria", [])),
            required_changed_paths=_string_list(getattr(config, "task_required_changed_paths", [])),
            forbidden_changed_paths=_string_list(getattr(config, "task_forbidden_changed_paths", [])),
            required_final_response_substrings=_string_list(
                getattr(config, "task_required_final_response_substrings", [])
            ),
            forbidden_final_response_substrings=_string_list(
                getattr(config, "task_forbidden_final_response_substrings", [])
            ),
        )

    @property
    def configured(self) -> bool:
        return any((
            self.success_criteria,
            self.required_changed_paths,
            self.forbidden_changed_paths,
            self.required_final_response_substrings,
            self.forbidden_final_response_substrings,
        ))

    @property
    def deterministic(self) -> bool:
        return any((
            self.required_changed_paths,
            self.forbidden_changed_paths,
            self.required_final_response_substrings,
            self.forbidden_final_response_substrings,
        ))

    def to_dict(self) -> dict[str, Any]:
        return {
            "success_criteria": list(self.success_criteria),
            "required_changed_paths": list(self.required_changed_paths),
            "forbidden_changed_paths": list(self.forbidden_changed_paths),
            "required_final_response_substrings": list(self.required_final_response_substrings),
            "forbidden_final_response_substrings": list(self.forbidden_final_response_substrings),
        }


@dataclass(frozen=True)
class TaskConstraintEvaluation:
    status: str
    message: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    @property
    def failed(self) -> bool:
        return self.status == "failed"

    @property
    def skipped(self) -> bool:
        return self.status == "skipped"


class TaskConstraintVerifier:
    """Verifies deterministic task constraints against trajectory evidence."""

    def __init__(self, spec: TaskConstraintSpec | None = None, *, workspace_root: str | Path = ".") -> None:
        self.spec = spec or TaskConstraintSpec()
        self.workspace_root = Path(workspace_root).expanduser().resolve()

    @classmethod
    def from_config(cls, config: Any) -> "TaskConstraintVerifier":
        return cls(
            TaskConstraintSpec.from_config(config),
            workspace_root=getattr(config, "workspace_root", "."),
        )

    @property
    def configured(self) -> bool:
        return self.spec.configured

    def verify(self, state: AgentState, final_text: str) -> TaskConstraintEvaluation:
        changed_paths = _changed_paths(state, self.workspace_root)
        metadata: dict[str, Any] = {
            "deterministic": self.spec.deterministic,
            "success_criteria": list(self.spec.success_criteria),
            "changed_paths": list(changed_paths),
            "required_changed_paths": [],
            "forbidden_changed_paths": [],
            "required_final_response_substrings": [],
            "forbidden_final_response_substrings": [],
            "violations": [],
        }

        if not self.spec.configured:
            metadata["violation_count"] = 0
            return TaskConstraintEvaluation(
                status="skipped",
                message="No task constraints configured.",
                metadata=metadata,
            )

        for pattern in self.spec.required_changed_paths:
            matches = _matching_paths(pattern, changed_paths)
            payload = {"pattern": pattern, "matches": matches}
            metadata["required_changed_paths"].append(payload)
            if not matches:
                metadata["violations"].append({
                    "type": "required_changed_path_missing",
                    "pattern": pattern,
                    "message": f"Required changed path was not modified: {pattern}",
                })

        for pattern in self.spec.forbidden_changed_paths:
            matches = _matching_paths(pattern, changed_paths)
            payload = {"pattern": pattern, "matches": matches}
            metadata["forbidden_changed_paths"].append(payload)
            if matches:
                metadata["violations"].append({
                    "type": "forbidden_changed_path_modified",
                    "pattern": pattern,
                    "matches": matches,
                    "message": f"Forbidden changed path was modified: {pattern}",
                })

        for text in self.spec.required_final_response_substrings:
            present = text in final_text
            metadata["required_final_response_substrings"].append({
                "substring": text,
                "present": present,
            })
            if not present:
                metadata["violations"].append({
                    "type": "required_final_response_missing",
                    "substring": text,
                    "message": "Required final response substring was not present.",
                })

        for text in self.spec.forbidden_final_response_substrings:
            present = text in final_text
            metadata["forbidden_final_response_substrings"].append({
                "substring": text,
                "present": present,
            })
            if present:
                metadata["violations"].append({
                    "type": "forbidden_final_response_present",
                    "substring": text,
                    "message": "Forbidden final response substring was present.",
                })

        metadata["violation_count"] = len(metadata["violations"])

        if not self.spec.deterministic:
            return TaskConstraintEvaluation(
                status="skipped",
                message="Task success criteria recorded for audit; no deterministic constraints configured.",
                metadata=metadata,
            )

        if metadata["violations"]:
            return TaskConstraintEvaluation(
                status="failed",
                message=f"Task constraints failed: {len(metadata['violations'])} violation(s).",
                metadata=metadata,
            )

        return TaskConstraintEvaluation(
            status="passed",
            message="All deterministic task constraints passed.",
            metadata=metadata,
        )


def _changed_paths(state: AgentState, workspace_root: Path) -> list[str]:
    paths: list[str] = []
    for step in state.trajectory:
        if step.observation.is_error:
            continue
        patch = step.observation.metadata.get("patch")
        if not isinstance(patch, Mapping):
            continue
        raw_path = patch.get("path")
        if raw_path in (None, ""):
            continue
        paths.append(_normalize_path(raw_path, workspace_root))
    return _unique(paths)


def _normalize_path(raw_path: Any, workspace_root: Path) -> str:
    path = Path(str(raw_path)).expanduser()
    if not path.is_absolute():
        path = workspace_root / path
    try:
        resolved = path.resolve(strict=False)
        relative = resolved.relative_to(workspace_root)
        return _posix(relative)
    except ValueError:
        return _posix(path)


def _matching_paths(pattern: str, changed_paths: list[str]) -> list[str]:
    normalized_pattern = _normalize_pattern(pattern)
    matches = [
        path for path in changed_paths
        if fnmatch.fnmatch(path, normalized_pattern) or fnmatch.fnmatch(Path(path).name, normalized_pattern)
    ]
    return sorted(matches)


def _normalize_pattern(pattern: str) -> str:
    return pattern.replace("\\", "/")


def _posix(path: Path) -> str:
    return "/".join(path.parts)


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
