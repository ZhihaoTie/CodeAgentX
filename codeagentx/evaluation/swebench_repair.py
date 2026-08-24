"""Build diagnostic repair tasks from annotated SWE-bench reports."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .benchmark import BenchmarkTaskSpec


SWEBENCH_REPAIR_BENCHMARK_SCHEMA_VERSION = "codeagentx.swebench_repair_benchmark.v1"
DEFAULT_REPAIR_MAX_FAILURE_EXCERPT_CHARS = 2_500
DEFAULT_REPAIR_MAX_PREVIOUS_PATCH_CHARS = 4_000


@dataclass(frozen=True)
class SWEbenchRepairBenchmarkArtifact:
    """Manifest for a generated diagnostic repair benchmark spec."""

    output_path: str
    source_report_path: str
    repair_task_count: int
    task_ids: list[str] = field(default_factory=list)
    included_resolved: bool = False
    public_benchmark_fairness: bool = False
    leakage_risk: str = (
        "contains official evaluator feedback; do not report as a public "
        "SWE-bench score"
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SWEBENCH_REPAIR_BENCHMARK_SCHEMA_VERSION,
            "output_path": self.output_path,
            "source_report_path": self.source_report_path,
            "repair_task_count": self.repair_task_count,
            "task_ids": list(self.task_ids),
            "included_resolved": self.included_resolved,
            "public_benchmark_fairness": self.public_benchmark_fairness,
            "leakage_risk": self.leakage_risk,
        }


def build_swebench_repair_tasks_from_report(
    report: Mapping[str, Any],
    *,
    report_path: str | Path | None = None,
    task_ids: list[str] | None = None,
    limit: int | None = None,
    include_resolved: bool = False,
    max_failure_excerpt_chars: int = DEFAULT_REPAIR_MAX_FAILURE_EXCERPT_CHARS,
    max_previous_patch_chars: int = DEFAULT_REPAIR_MAX_PREVIOUS_PATCH_CHARS,
) -> list[BenchmarkTaskSpec]:
    """Create benchmark tasks enriched with official SWE-bench failure evidence."""

    if limit is not None and limit <= 0:
        raise ValueError("SWE-bench repair limit must be greater than 0")
    wanted = {str(item) for item in task_ids or []}
    tasks_by_id = {
        str(task.get("task_id")): task
        for task in _list(report.get("tasks"))
        if isinstance(task, Mapping) and task.get("task_id") is not None
    }

    repair_tasks: list[BenchmarkTaskSpec] = []
    for result in _list(report.get("results")):
        if not isinstance(result, Mapping) or result.get("task_id") is None:
            continue
        task_id = str(result.get("task_id"))
        task = tasks_by_id.get(task_id)
        if task is None or not _is_swebench_task(task):
            continue
        instance_id = _swebench_instance_id(task, task_id)
        if wanted and task_id not in wanted and instance_id not in wanted:
            continue
        if result.get("official_resolved") is True and not include_resolved:
            continue
        if (
            "official_resolved" not in result
            and "official_status" not in result
            and not include_resolved
        ):
            continue

        repair_tasks.append(
            _build_repair_task(
                task,
                result,
                report_path=report_path,
                max_failure_excerpt_chars=max_failure_excerpt_chars,
                max_previous_patch_chars=max_previous_patch_chars,
            )
        )
        if limit is not None and len(repair_tasks) >= limit:
            break

    if not repair_tasks:
        raise ValueError("annotated report contains no SWE-bench tasks needing repair")
    return repair_tasks


def write_swebench_repair_benchmark_spec(
    report_path: str | Path,
    output_path: str | Path,
    *,
    task_ids: list[str] | None = None,
    limit: int | None = None,
    include_resolved: bool = False,
    max_failure_excerpt_chars: int = DEFAULT_REPAIR_MAX_FAILURE_EXCERPT_CHARS,
    max_previous_patch_chars: int = DEFAULT_REPAIR_MAX_PREVIOUS_PATCH_CHARS,
) -> SWEbenchRepairBenchmarkArtifact:
    """Write a benchmark spec for diagnostic repair passes."""

    source = Path(report_path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("benchmark report JSON must be an object")
    tasks = build_swebench_repair_tasks_from_report(
        payload,
        report_path=source,
        task_ids=task_ids,
        limit=limit,
        include_resolved=include_resolved,
        max_failure_excerpt_chars=max_failure_excerpt_chars,
        max_previous_patch_chars=max_previous_patch_chars,
    )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    artifact = SWEbenchRepairBenchmarkArtifact(
        output_path=str(output),
        source_report_path=str(source),
        repair_task_count=len(tasks),
        task_ids=[task.task_id for task in tasks],
        included_resolved=include_resolved,
    )
    output.write_text(
        json.dumps(
            {
                **artifact.to_dict(),
                "defaults": {
                    "enable_failure_reflection": True,
                    "enable_retry_strategy_matrix": True,
                    "enable_tool_planning_guidance": True,
                    "enable_git_diff_artifact": True,
                },
                "tasks": [task.to_dict() for task in tasks],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return artifact


def _build_repair_task(
    task: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    report_path: str | Path | None,
    max_failure_excerpt_chars: int,
    max_previous_patch_chars: int,
) -> BenchmarkTaskSpec:
    payload = dict(task)
    payload["goal"] = _repair_goal(
        task,
        result,
        report_path=report_path,
        max_failure_excerpt_chars=max_failure_excerpt_chars,
        max_previous_patch_chars=max_previous_patch_chars,
    )
    payload["workspace_root"] = (
        result.get("original_workspace_root")
        or task.get("workspace_root")
        or "."
    )
    payload["tags"] = _unique([
        *_string_list(task.get("tags")),
        "repair-pass",
        "official-feedback",
        "diagnostic-only",
    ])

    metadata = _scrub_repair_metadata(task.get("metadata"))
    metadata["swebench_repair"] = {
        "source_task_id": str(result.get("task_id")),
        "source_official_resolved": result.get("official_resolved"),
        "source_official_status": result.get("official_status"),
        "source_failure_summary": result.get("official_failure_summary"),
        "source_log_path": result.get("official_log_path"),
        "source_test_output_path": result.get("official_test_output_path"),
        "public_benchmark_fairness": False,
        "leakage_risk": (
            "This repair task may include official evaluator feedback and "
            "must not be reported as a fair public SWE-bench score."
        ),
    }
    payload["metadata"] = metadata
    return BenchmarkTaskSpec.from_dict(payload)


def _scrub_repair_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    metadata = json.loads(json.dumps(dict(value), ensure_ascii=False))
    swebench = metadata.get("swebench")
    if isinstance(swebench, dict):
        nested = swebench.get("metadata")
        if isinstance(nested, dict):
            for key in ("patch", "test_patch", "gold_patch"):
                nested.pop(key, None)
    return metadata


def _repair_goal(
    task: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    report_path: str | Path | None,
    max_failure_excerpt_chars: int,
    max_previous_patch_chars: int,
) -> str:
    base_goal = str(task.get("goal") or result.get("goal") or "").strip()
    previous_patch = _truncate_block(
        _previous_patch(result, report_path=report_path),
        max_previous_patch_chars,
    )
    failure_excerpt = _truncate_block(
        str(result.get("official_failure_excerpt") or "").strip(),
        max_failure_excerpt_chars,
    )
    fail_to_pass_failed = _string_list(result.get("official_fail_to_pass_failed"))
    pass_to_pass_failed = _string_list(result.get("official_pass_to_pass_failed"))

    lines = [
        base_goal,
        "",
        "Diagnostic repair pass:",
        "A previous CodeAgent-X patch did not pass the official SWE-bench evaluator.",
        "Use the evidence below to repair the issue from the clean base workspace.",
        "",
        "Fairness note:",
        "- This repair prompt may contain official evaluator feedback.",
        "- Do not report this run as a fair public SWE-bench benchmark score.",
        "- Use it as an engineering diagnostic and failure-recovery pass.",
        "",
        "Official evaluator outcome:",
        f"- status: {_text(result.get('official_status'))}",
        f"- resolved: {_text(result.get('official_resolved'))}",
        f"- patch_applied: {_text(result.get('official_patch_successfully_applied'))}",
    ]
    if fail_to_pass_failed:
        lines.extend([
            "- FAIL_TO_PASS failures:",
            *_bullets(fail_to_pass_failed),
        ])
    if pass_to_pass_failed:
        lines.extend([
            "- PASS_TO_PASS regressions:",
            *_bullets(pass_to_pass_failed),
        ])
    if result.get("official_failure_summary"):
        lines.extend([
            "",
            "Failure summary:",
            str(result.get("official_failure_summary")).strip(),
        ])
    if failure_excerpt:
        lines.extend([
            "",
            "Failure excerpt:",
            "```text",
            failure_excerpt,
            "```",
        ])
    if previous_patch:
        lines.extend([
            "",
            "Previous patch for diagnosis only:",
            "```diff",
            previous_patch,
            "```",
        ])
    lines.extend([
        "",
        "Repair requirements:",
        "- Start from the current clean workspace, not from assumptions about the previous run.",
        "- Regenerate a minimal patch that applies cleanly to the base commit.",
        "- Run the most focused relevant local tests you can identify.",
        "- Do not create or leave scratch/debug/reproduction files in the final diff.",
        "- Return a concise summary of the repair and verification.",
    ])
    return "\n".join(lines)


def _previous_patch(result: Mapping[str, Any], *, report_path: str | Path | None) -> str:
    for artifact in _list(result.get("artifacts")):
        if not isinstance(artifact, Mapping) or artifact.get("kind") != "git_diff":
            continue
        patch_path = artifact.get("patch_path")
        if not patch_path:
            continue
        path = _resolve_report_path(str(patch_path), report_path)
        if path.exists() and path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")
    return ""


def _resolve_report_path(raw_path: str, report_path: str | Path | None) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path
    if path.exists():
        return path
    if report_path is not None:
        candidate = Path(report_path).expanduser().parent / path
        if candidate.exists():
            return candidate
    return path


def _is_swebench_task(task: Mapping[str, Any]) -> bool:
    metadata = task.get("metadata", {})
    return isinstance(metadata, Mapping) and isinstance(metadata.get("swebench"), Mapping)


def _swebench_instance_id(task: Mapping[str, Any], fallback: str) -> str:
    metadata = task.get("metadata", {})
    if isinstance(metadata, Mapping):
        swebench = metadata.get("swebench", {})
        if isinstance(swebench, Mapping) and swebench.get("instance_id"):
            return str(swebench["instance_id"])
    return fallback


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _string_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple):
        return [str(item) for item in value]
    return []


def _unique(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item not in seen:
            result.append(item)
            seen.add(item)
    return result


def _bullets(items: list[str]) -> list[str]:
    return [f"  - {item}" for item in items]


def _truncate_block(text: str, limit: int) -> str:
    text = text.strip()
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    return text[: limit - 40].rstrip() + "\n... [truncated for repair prompt]"


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)
