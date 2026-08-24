"""Extract verified memory records from completed agent state."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

from codeagentx.agent.state import AgentState, TaskStatus

from .schema import MemoryRecord


class MemoryExtractor:
    """Build durable memory only from verified successful trajectories."""

    def extract(
        self,
        state: AgentState,
        *,
        evidence_path: str | Path | None = None,
        workspace_root: str | Path | None = None,
    ) -> MemoryRecord | None:
        if state.status != TaskStatus.SUCCEEDED:
            return None
        verification = state.verification_report
        if not isinstance(verification, Mapping) or verification.get("status") != "passed":
            return None

        changed_files = _changed_files(state, workspace_root=workspace_root)
        tests = _tests_from_verification(verification)
        symptoms = _symptoms(state)
        root_cause = _root_cause(state, verification, changed_files)
        strategy = _strategy(state, changed_files)
        language = _language(changed_files)
        task_type = _task_type(state, symptoms, changed_files)
        applicability = _applicability(
            language=language,
            symptoms=symptoms,
            changed_files=changed_files,
        )
        memory_id = _memory_id(
            task_type=task_type,
            language=language,
            goal=state.goal,
            changed_files=changed_files,
            symptoms=symptoms,
            strategy=strategy,
        )

        return MemoryRecord(
            memory_id=memory_id,
            task_id=state.task_id,
            task_type=task_type,
            language=language,
            source_goal=state.goal,
            symptoms=symptoms,
            root_cause=root_cause,
            strategy=strategy,
            changed_files=changed_files,
            tests=tests,
            evidence_path=str(evidence_path or ""),
            applicability=applicability,
            verified=True,
            metadata={
                "verification_summary": str(verification.get("summary", "") or ""),
                "turns": state.turn_index,
                "tool_calls": state.tool_call_count(),
                "reflection_retry_count": state.reflection_retry_count(),
            },
        )


def _changed_files(
    state: AgentState,
    *,
    workspace_root: str | Path | None = None,
) -> list[str]:
    paths: list[str] = []
    root = Path(workspace_root).expanduser().resolve() if workspace_root else None
    for step in state.trajectory:
        if step.observation.is_error:
            continue
        patch = step.observation.metadata.get("patch")
        if not isinstance(patch, Mapping):
            continue
        path = patch.get("path")
        if path:
            paths.append(_relative_path(path, root))
    return _unique(paths)


def _tests_from_verification(report: Mapping[str, Any]) -> list[str]:
    tests: list[str] = []
    for check in report.get("checks", []) or []:
        if not isinstance(check, Mapping):
            continue
        metadata = check.get("metadata", {})
        if not isinstance(metadata, Mapping):
            continue
        command = metadata.get("command")
        if command:
            tests.append(str(command))
        test_result = metadata.get("test_result", {})
        if isinstance(test_result, Mapping):
            for name in test_result.get("failure_names", []) or []:
                if name:
                    tests.append(str(name))
    return _unique(tests)


def _symptoms(state: AgentState) -> list[str]:
    symptoms: list[str] = []
    reflection = state.reflection_report
    if isinstance(reflection, Mapping):
        for signal in reflection.get("signals", []) or []:
            if not isinstance(signal, Mapping):
                continue
            category = signal.get("category")
            message = signal.get("message")
            if category:
                symptoms.append(str(category))
            if message:
                symptoms.append(str(message))
    verification = state.verification_report
    if isinstance(verification, Mapping):
        if not symptoms:
            symptoms.append("task goal: " + state.goal[:300])
        summary = str(verification.get("summary", "") or "")
        if summary and summary != "All configured verification checks passed.":
            symptoms.append(summary)
    return _unique(symptoms)[:10]


def _root_cause(
    state: AgentState,
    verification: Mapping[str, Any],
    changed_files: list[str],
) -> str:
    reflection = state.reflection_report
    if isinstance(reflection, Mapping):
        summary = str(reflection.get("summary", "") or "").strip()
        if summary:
            return summary[:500]
    if changed_files:
        return (
            "The task required a targeted implementation change in "
            + ", ".join(changed_files[:5])
            + " to satisfy deterministic verification."
        )[:500]
    return str(verification.get("summary", "") or "Verified successful repair.")[:500]


def _strategy(state: AgentState, changed_files: list[str]) -> str:
    retry_reports = [
        report
        for report in state.reflection_retry_reports
        if isinstance(report, Mapping)
    ]
    if retry_reports:
        strategy = retry_reports[-1].get("strategy")
        if isinstance(strategy, Mapping):
            name = strategy.get("strategy")
            actions = strategy.get("actions", [])
            action_text = ", ".join(str(item) for item in actions[:4]) if isinstance(actions, list) else ""
            if name and action_text:
                return f"Used retry strategy {name}: {action_text}."
            if name:
                return f"Used retry strategy {name}."
    if changed_files:
        return "Applied a targeted patch to " + ", ".join(changed_files[:5]) + " and reran verification."
    return "Validated the task with deterministic verification."


def _language(paths: list[str]) -> str:
    languages = {_language_for_suffix(Path(path).suffix.lower()) for path in paths}
    languages.discard("unknown")
    if not languages:
        return "unknown"
    if len(languages) == 1:
        return next(iter(languages))
    return "multi-language"


def _language_for_suffix(suffix: str) -> str:
    return {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
    }.get(suffix, "unknown")


def _relative_path(path: Any, root: Path | None) -> str:
    raw = str(path).replace("\\", "/")
    candidate = Path(str(path)).expanduser()
    if root is not None:
        try:
            return candidate.resolve().relative_to(root).as_posix()
        except (OSError, ValueError):
            pass
    return raw


def _task_type(state: AgentState, symptoms: list[str], changed_files: list[str]) -> str:
    text = " ".join([state.goal, *symptoms]).lower()
    if "test" in text or "verification" in text or "failed" in text:
        return "test_driven_repair"
    if changed_files:
        return "code_repair"
    return "software_task"


def _applicability(
    *,
    language: str,
    symptoms: list[str],
    changed_files: list[str],
) -> str:
    pieces = []
    if language != "unknown":
        pieces.append(f"language={language}")
    if symptoms:
        pieces.append("similar symptoms: " + "; ".join(symptoms[:3]))
    if changed_files:
        stems = [Path(path).stem for path in changed_files[:3]]
        pieces.append("near files/symbols like " + ", ".join(stems))
    if not pieces:
        return "Use only when the task shape and verification evidence are clearly similar."
    return "Use only when " + " and ".join(pieces) + "."


def _memory_id(
    *,
    task_type: str,
    language: str,
    goal: str,
    changed_files: list[str],
    symptoms: list[str],
    strategy: str,
) -> str:
    raw = "\n".join([
        task_type,
        language,
        goal,
        ",".join(changed_files),
        ",".join(symptoms),
        strategy,
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value).strip()
        key = item.lower()
        if not item or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result
