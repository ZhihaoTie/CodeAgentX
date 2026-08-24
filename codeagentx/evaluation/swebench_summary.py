"""SWE-bench experiment summary aggregation helpers."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping


SWEBENCH_EXPERIMENT_SUMMARY_SCHEMA_VERSION = "codeagentx.swebench_experiment_summary.v1"


def build_swebench_experiment_summary(
    report_paths: list[str | Path],
) -> dict[str, Any]:
    """Aggregate annotated SWE-bench benchmark reports into one experiment summary."""

    if not report_paths:
        raise ValueError("at least one SWE-bench report path is required")

    rows: list[dict[str, Any]] = []
    normalized_report_paths: list[str] = []
    for raw_path in report_paths:
        report_path = Path(raw_path).expanduser()
        payload = _load_report(report_path)
        normalized_report_paths.append(str(report_path))
        rows.extend(_task_rows(payload, source_report_path=report_path))

    task_count = len(rows)
    evaluated_tasks = sum(1 for row in rows if row["official_evaluated"])
    official_resolved_tasks = sum(1 for row in rows if row["official_resolved"] is True)
    official_error_tasks = sum(
        1 for row in rows if row["failure_category"] == "evaluator_error"
    )
    official_missing_tasks = sum(1 for row in rows if not row["official_evaluated"])
    patch_generated_tasks = sum(1 for row in rows if row["patch_generated"])
    patch_applied_tasks = sum(1 for row in rows if row["official_patch_successfully_applied"] is True)
    category_counts = dict(Counter(row["failure_category"] for row in rows))

    return {
        "schema_version": SWEBENCH_EXPERIMENT_SUMMARY_SCHEMA_VERSION,
        "report_count": len(normalized_report_paths),
        "report_paths": normalized_report_paths,
        "task_count": task_count,
        "unique_task_count": len({row["task_id"] for row in rows}),
        "evaluated_tasks": evaluated_tasks,
        "official_resolved_tasks": official_resolved_tasks,
        "official_unresolved_tasks": evaluated_tasks - official_resolved_tasks,
        "official_non_error_unresolved_tasks": max(
            evaluated_tasks - official_resolved_tasks - official_error_tasks,
            0,
        ),
        "official_error_tasks": official_error_tasks,
        "official_missing_tasks": official_missing_tasks,
        "official_resolved_rate": _ratio(official_resolved_tasks, task_count),
        "evaluated_official_resolved_rate": _ratio(official_resolved_tasks, evaluated_tasks),
        "patch_generated_tasks": patch_generated_tasks,
        "patch_applied_tasks": patch_applied_tasks,
        "failure_category_counts": category_counts,
        "average_tool_calls": _average_metric(rows, "tool_calls"),
        "average_budget_total_tokens": _average_metric(rows, "budget_total_tokens"),
        "average_git_diff_patch_bytes": _average_metric(rows, "git_diff_patch_bytes"),
        "average_git_diff_changed_files": _average_metric(rows, "git_diff_changed_files"),
        "average_git_diff_forbidden_paths": _average_metric(
            rows,
            "git_diff_forbidden_path_count",
        ),
        "tasks": rows,
    }


def render_swebench_experiment_summary_markdown(summary: Mapping[str, Any]) -> str:
    """Render an aggregated SWE-bench experiment summary as Markdown."""

    rows = _list(summary.get("tasks"))
    lines = [
        "# SWE-bench Experiment Summary",
        "",
        "## Summary",
        "",
        _markdown_table(
            ["Metric", "Value"],
            [
                ("report_count", summary.get("report_count")),
                ("task_count", summary.get("task_count")),
                ("unique_task_count", summary.get("unique_task_count")),
                ("evaluated_tasks", summary.get("evaluated_tasks")),
                ("official_resolved_tasks", summary.get("official_resolved_tasks")),
                ("official_unresolved_tasks", summary.get("official_unresolved_tasks")),
                (
                    "official_non_error_unresolved_tasks",
                    summary.get("official_non_error_unresolved_tasks"),
                ),
                ("official_error_tasks", summary.get("official_error_tasks")),
                ("official_missing_tasks", summary.get("official_missing_tasks")),
                ("official_resolved_rate", _percent(summary.get("official_resolved_rate"))),
                (
                    "evaluated_official_resolved_rate",
                    _percent(summary.get("evaluated_official_resolved_rate")),
                ),
                ("patch_generated_tasks", summary.get("patch_generated_tasks")),
                ("patch_applied_tasks", summary.get("patch_applied_tasks")),
                ("average_tool_calls", _number(summary.get("average_tool_calls"))),
                (
                    "average_budget_total_tokens",
                    _number(summary.get("average_budget_total_tokens")),
                ),
                (
                    "average_git_diff_patch_bytes",
                    _number(summary.get("average_git_diff_patch_bytes")),
                ),
                (
                    "average_git_diff_forbidden_paths",
                    _number(summary.get("average_git_diff_forbidden_paths")),
                ),
            ],
        ),
        "",
        "## Failure Categories",
        "",
        _failure_category_table(_mapping(summary.get("failure_category_counts"))),
        "",
        "## Tasks",
        "",
        _tasks_table(rows),
        "",
    ]
    return "\n".join(lines)


def write_swebench_experiment_summary(
    report_paths: list[str | Path],
    output_path: str | Path,
    *,
    markdown_output_path: str | Path | None = None,
) -> dict[str, Path | dict[str, Any]]:
    """Write JSON and optional Markdown summary artifacts."""

    summary = build_swebench_experiment_summary(report_paths)
    output = Path(output_path).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    markdown_path: Path | None = None
    if markdown_output_path is not None:
        markdown_path = Path(markdown_output_path).expanduser()
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(
            render_swebench_experiment_summary_markdown(summary),
            encoding="utf-8",
        )

    return {
        "summary": summary,
        "summary_path": output,
        "markdown_path": markdown_path,
    }


def _load_report(report_path: Path) -> Mapping[str, Any]:
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"SWE-bench report JSON must be an object: {report_path}")
    return payload


def _task_rows(
    report: Mapping[str, Any],
    *,
    source_report_path: Path,
) -> list[dict[str, Any]]:
    run_id = _text(report.get("run_id") or source_report_path.parent.name)
    created_at = _text(report.get("created_at"))
    output_dir = _text(report.get("output_dir"))
    memory_policy = _text(_mapping(report.get("memory_policy")).get("policy"))
    official = _mapping(report.get("swebench_official_evaluation"))
    official_results_path = _text(official.get("results_path"))

    rows: list[dict[str, Any]] = []
    for item in _list(report.get("results")):
        result = _mapping(item)
        if not result:
            continue
        task_id = _text(result.get("task_id"))
        if not task_id:
            continue
        metrics = _mapping(result.get("metrics"))
        official_resolved = _official_resolved(result, metrics)
        official_status = _text(result.get("official_status") or metrics.get("swebench_official_status"))
        official_error = _text(result.get("official_error"))
        fail_to_pass_failed = _string_items(result.get("official_fail_to_pass_failed"))
        pass_to_pass_failed = _string_items(result.get("official_pass_to_pass_failed"))
        patch_generated = _positive_number(metrics.get("git_diff_patch_bytes"))
        patch_applied = _optional_bool(
            result.get(
                "official_patch_successfully_applied",
                metrics.get("swebench_official_patch_successfully_applied"),
            )
        )
        official_evaluated = (
            isinstance(official_resolved, bool)
            or bool(official_status)
            or bool(official_error)
            or patch_applied is not None
            or bool(fail_to_pass_failed)
            or bool(pass_to_pass_failed)
        )
        failure_category = _failure_category(
            official_resolved=official_resolved,
            official_evaluated=official_evaluated,
            official_status=official_status,
            official_error=official_error,
            patch_generated=patch_generated,
            patch_applied=patch_applied,
            fail_to_pass_failed=fail_to_pass_failed,
            pass_to_pass_failed=pass_to_pass_failed,
        )
        rows.append({
            "task_id": task_id,
            "run_id": run_id,
            "created_at": created_at,
            "source_report_path": str(source_report_path),
            "output_dir": output_dir,
            "memory_policy": memory_policy,
            "local_status": _text(result.get("status")),
            "local_resolved": _optional_bool(result.get("resolved")),
            "verification_status": _text(result.get("verification_status")),
            "official_evaluated": official_evaluated,
            "official_resolved": official_resolved,
            "official_status": official_status,
            "official_error": official_error,
            "official_results_path": official_results_path,
            "official_patch_successfully_applied": patch_applied,
            "official_fail_to_pass_failed": fail_to_pass_failed,
            "official_pass_to_pass_failed": pass_to_pass_failed,
            "official_fail_to_pass_failed_count": len(fail_to_pass_failed),
            "official_pass_to_pass_failed_count": len(pass_to_pass_failed),
            "patch_generated": patch_generated,
            "tool_calls": _number_value(metrics.get("tool_calls")),
            "budget_total_tokens": _number_value(metrics.get("budget_total_tokens")),
            "git_diff_patch_bytes": _number_value(metrics.get("git_diff_patch_bytes")),
            "git_diff_changed_files": _number_value(metrics.get("git_diff_changed_files")),
            "git_diff_forbidden_path_count": _number_value(
                metrics.get("git_diff_forbidden_path_count")
            ),
            "patch_policy_changed_lines": _number_value(metrics.get("patch_policy_changed_lines")),
            "failure_category": failure_category,
        })
    return rows


def _failure_category(
    *,
    official_resolved: bool | None,
    official_evaluated: bool,
    official_status: str,
    official_error: str,
    patch_generated: bool,
    patch_applied: bool | None,
    fail_to_pass_failed: list[str],
    pass_to_pass_failed: list[str],
) -> str:
    if official_resolved is True:
        return "resolved"
    if not official_evaluated:
        return "official_missing"
    if official_error or official_status.lower() in {"error", "errored"}:
        return "evaluator_error"
    if not patch_generated:
        return "empty_patch_or_no_diff"
    if patch_applied is False:
        return "patch_apply_failed"
    if fail_to_pass_failed:
        return "hidden_tests_failed"
    if pass_to_pass_failed:
        return "regression_failed"
    if official_resolved is False:
        return "unresolved_unknown"
    return "unknown"


def _tasks_table(rows: list[Any]) -> str:
    table_rows: list[tuple[Any, ...]] = []
    for item in rows:
        row = _mapping(item)
        table_rows.append((
            row.get("task_id"),
            row.get("run_id"),
            _yes_no_optional(row.get("official_resolved")),
            row.get("failure_category"),
            _yes_no(row.get("patch_generated")),
            _yes_no_optional(row.get("official_patch_successfully_applied")),
            _compact_items(_string_items(row.get("official_fail_to_pass_failed"))),
            _compact_items(_string_items(row.get("official_pass_to_pass_failed"))),
            _number(row.get("tool_calls")),
            _number(row.get("budget_total_tokens")),
            _number(row.get("git_diff_patch_bytes")),
        ))
    return _markdown_table(
        [
            "Task",
            "Run",
            "Official",
            "Category",
            "Patch Generated",
            "Patch Applied",
            "F2P Failed",
            "P2P Failed",
            "Tools",
            "Tokens",
            "Patch Bytes",
        ],
        table_rows,
    )


def _failure_category_table(category_counts: Mapping[str, Any]) -> str:
    ordered_rows = sorted(
        ((key, value) for key, value in category_counts.items()),
        key=lambda item: (-int(item[1]), item[0]) if isinstance(item[1], int) else (0, item[0]),
    )
    return _markdown_table(["Category", "Count"], ordered_rows)


def _official_resolved(
    result: Mapping[str, Any],
    metrics: Mapping[str, Any],
) -> bool | None:
    if "official_resolved" in result:
        return _optional_bool(result.get("official_resolved"))
    return _optional_bool(metrics.get("swebench_official_resolved"))


def _average_metric(rows: list[Mapping[str, Any]], key: str) -> float | None:
    values = [
        value
        for row in rows
        if isinstance((value := row.get(key)), (int, float)) and not isinstance(value, bool)
    ]
    if not values:
        return None
    return sum(float(value) for value in values) / len(values)


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _number_value(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def _number(value: Any) -> str:
    if isinstance(value, bool):
        return ""
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    if isinstance(value, int):
        return str(value)
    return ""


def _percent(value: Any) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return ""
    return f"{value:.1%}"


def _yes_no(value: Any) -> str:
    return "yes" if bool(value) else "no"


def _yes_no_optional(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    return ""


def _string_items(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple):
        return [str(item) for item in value]
    return []


def _compact_items(values: list[str], *, limit: int = 5) -> str:
    if not values:
        return ""
    visible = values[:limit]
    suffix = f", +{len(values) - limit} more" if len(values) > limit else ""
    return ", ".join(visible) + suffix


def _markdown_table(headers: list[str], rows: list[tuple[Any, ...]]) -> str:
    if not rows:
        rows = [tuple("" for _ in headers)]
    rendered_headers = [_escape_cell(header) for header in headers]
    rendered_rows = [
        [_escape_cell(_text(cell)) for cell in row]
        for row in rows
    ]
    lines = [
        "| " + " | ".join(rendered_headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rendered_rows)
    return "\n".join(lines)


def _escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
