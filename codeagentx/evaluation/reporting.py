"""Markdown rendering for benchmark report artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .benchmark import BENCHMARK_ABLATION_SCHEMA_VERSION, BENCHMARK_SCHEMA_VERSION


def render_benchmark_report_markdown(report: Mapping[str, Any]) -> str:
    """Render a benchmark or ablation report JSON payload as Markdown."""

    schema = report.get("schema_version")
    if schema == BENCHMARK_SCHEMA_VERSION:
        return _render_single_report(report)
    if schema == BENCHMARK_ABLATION_SCHEMA_VERSION:
        return _render_ablation_report(report)
    raise ValueError(f"unsupported benchmark report schema: {schema!r}")


def render_benchmark_report_file(path: str | Path) -> str:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("benchmark report JSON must be an object")
    return render_benchmark_report_markdown(payload)


def save_benchmark_report_markdown(
    report_path: str | Path,
    output_path: str | Path | None = None,
) -> Path:
    report_path = Path(report_path)
    markdown = render_benchmark_report_file(report_path)
    output = Path(output_path) if output_path is not None else report_path.with_suffix(".md")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown, encoding="utf-8")
    return output


def _render_single_report(report: Mapping[str, Any]) -> str:
    summary = _mapping(report.get("summary"))
    results = _list(report.get("results"))
    swebench_section = _swebench_official_section(report)
    swebench_failure_section = _swebench_failure_details_section(results)
    lines = [
        "# CodeAgent-X Benchmark Report",
        "",
        f"- Run ID: `{_text(report.get('run_id'))}`",
        f"- Created: `{_text(report.get('created_at'))}`",
        f"- Output Dir: `{_text(report.get('output_dir'))}`",
        f"- Memory Policy: `{_text(_mapping(report.get('memory_policy')).get('policy'))}`",
        "",
        "## Summary",
        "",
        _summary_table(summary),
        "",
        *swebench_section,
        "## Task Results",
        "",
        _task_results_table(results),
        "",
        *swebench_failure_section,
    ]
    return "\n".join(lines)


def _render_ablation_report(report: Mapping[str, Any]) -> str:
    summary = _mapping(report.get("summary"))
    variant_results = _list(report.get("variant_results"))
    task_outcomes = _list(report.get("task_outcomes"))
    lines = [
        "# CodeAgent-X Benchmark Ablation Report",
        "",
        f"- Run ID: `{_text(report.get('run_id'))}`",
        f"- Created: `{_text(report.get('created_at'))}`",
        f"- Output Dir: `{_text(report.get('output_dir'))}`",
        f"- Baseline Variant: `{_text(summary.get('baseline_variant'))}`",
        f"- Memory Policy: `{_text(_ablation_memory_policy(variant_results))}`",
        "",
        "## Summary",
        "",
        _summary_table(summary),
        "",
        "## Variants",
        "",
        _variant_results_table(variant_results),
        "",
        "## Task Outcomes",
        "",
        _task_outcomes_table(task_outcomes),
        "",
    ]
    return "\n".join(lines)


def _summary_table(summary: Mapping[str, Any]) -> str:
    rows = [
        ("total_tasks", summary.get("total_tasks", summary.get("task_count"))),
        ("resolved_tasks", summary.get("resolved_tasks")),
        ("failed_tasks", summary.get("failed_tasks")),
        ("resolved_rate", _percent(summary.get("resolved_rate"))),
        ("first_pass_success_rate", _percent(summary.get("first_pass_success_rate"))),
        ("retry_recovery_rate", _percent(summary.get("retry_recovery_rate"))),
        ("average_tool_calls", _number(summary.get("average_tool_calls"))),
        ("average_budget_turns", _number(summary.get("average_budget_turns"))),
        ("average_budget_tool_calls", _number(summary.get("average_budget_tool_calls"))),
        ("average_budget_total_tokens", _number(summary.get("average_budget_total_tokens"))),
        (
            "average_budget_elapsed_seconds",
            _number(summary.get("average_budget_elapsed_seconds")),
        ),
        ("budget_exhausted_tasks", summary.get("budget_exhausted_tasks")),
        ("average_patch_changed_lines", _number(summary.get("average_patch_changed_lines"))),
        ("average_git_diff_patch_bytes", _number(summary.get("average_git_diff_patch_bytes"))),
        ("average_git_diff_changed_files", _number(summary.get("average_git_diff_changed_files"))),
        (
            "average_git_diff_forbidden_paths",
            _number(summary.get("average_git_diff_forbidden_paths")),
        ),
        ("average_memory_hits", _number(summary.get("average_memory_hits"))),
        ("average_memory_candidates", _number(summary.get("average_memory_candidates"))),
        ("average_memory_filtered", _number(summary.get("average_memory_filtered"))),
        (
            "average_memory_prompt_injected",
            _number(summary.get("average_memory_prompt_injected")),
        ),
        ("average_memory_stored", _number(summary.get("average_memory_stored"))),
        ("artifact_count", summary.get("artifact_count")),
    ]
    rows = [(key, value) for key, value in rows if value not in (None, "")]
    return _markdown_table(["Metric", "Value"], rows)


def _swebench_official_section(report: Mapping[str, Any]) -> list[str]:
    official = _mapping(report.get("swebench_official_evaluation"))
    if not official:
        return []
    rows = [
        ("results_path", official.get("results_path")),
        ("total_tasks", official.get("total_tasks")),
        ("evaluated_tasks", official.get("evaluated_tasks")),
        ("resolved_tasks", official.get("resolved_tasks")),
        ("unresolved_tasks", official.get("unresolved_tasks")),
        ("non_error_unresolved_tasks", official.get("non_error_unresolved_tasks")),
        ("error_tasks", official.get("error_tasks")),
        ("missing_tasks", official.get("missing_tasks")),
        ("resolved_rate", _percent(official.get("resolved_rate"))),
        ("evaluated_resolved_rate", _percent(official.get("evaluated_resolved_rate"))),
    ]
    rows = [(key, value) for key, value in rows if value not in (None, "")]
    return [
        "## SWE-bench Official Evaluation",
        "",
        _markdown_table(["Metric", "Value"], rows),
        "",
    ]


def _task_results_table(results: list[Any]) -> str:
    rows: list[tuple[Any, ...]] = []
    has_official = any(_has_official_swebench_result(_mapping(item)) for item in results)
    for item in results:
        result = _mapping(item)
        metrics = _mapping(result.get("metrics"))
        row = [
            result.get("task_id"),
            _yes_no(result.get("resolved")),
        ]
        if has_official:
            row.extend([
                _yes_no_optional(_official_resolved(result, metrics)),
                _text(result.get("official_status") or metrics.get("swebench_official_status")),
            ])
        row.extend([
            result.get("status"),
            result.get("verification_status"),
            _number(metrics.get("tool_calls")),
            _number(metrics.get("reflection_retry_count")),
            _number(metrics.get("memory_hit_count")),
            _number(metrics.get("memory_prompt_injected_count")),
            _number(metrics.get("patch_policy_changed_lines")),
            _number(metrics.get("git_diff_patch_bytes")),
            _yes_no(metrics.get("budget_exhausted")),
            _number(metrics.get("budget_total_tokens")),
        ])
        rows.append(tuple(row))

    headers = [
        "Task",
        "Resolved",
    ]
    if has_official:
        headers.extend(["Official Resolved", "Official Status"])
    headers.extend([
        "Status",
        "Verification",
        "Tools",
        "Retries",
        "Memory Hits",
        "Memory Injected",
        "Patch Lines",
        "Git Patch Bytes",
        "Budget Exhausted",
        "Budget Tokens",
    ])
    return _markdown_table(headers, rows)


def _swebench_failure_details_section(results: list[Any]) -> list[str]:
    rows: list[tuple[Any, ...]] = []
    for item in results:
        result = _mapping(item)
        if not _has_official_swebench_result(result):
            continue
        official_status = _text(result.get("official_status"))
        fail_to_pass_failed = _string_items(result.get("official_fail_to_pass_failed"))
        pass_to_pass_failed = _string_items(result.get("official_pass_to_pass_failed"))
        official_error = _text(result.get("official_error"))
        patch_applied = result.get("official_patch_successfully_applied")
        failure_summary = _text(result.get("official_failure_summary"))
        official_log_path = _text(result.get("official_log_path"))
        unresolved = result.get("official_resolved") is False
        if not (
            unresolved
            or fail_to_pass_failed
            or pass_to_pass_failed
            or official_error
            or isinstance(patch_applied, bool)
            or failure_summary
            or official_log_path
        ):
            continue
        rows.append((
            result.get("task_id"),
            official_status,
            _yes_no_optional(patch_applied),
            _compact_items(fail_to_pass_failed),
            _compact_items(pass_to_pass_failed),
            failure_summary,
            official_error,
            official_log_path,
        ))
    if not rows:
        return []
    return [
        "## SWE-bench Failure Details",
        "",
        _markdown_table(
            [
                "Task",
                "Official Status",
                "Patch Applied",
                "FAIL_TO_PASS Failures",
                "PASS_TO_PASS Failures",
                "Diagnostic",
                "Error",
                "Log",
            ],
            rows,
        ),
        "",
    ]


def _has_official_swebench_result(result: Mapping[str, Any]) -> bool:
    metrics = _mapping(result.get("metrics"))
    return (
        "official_resolved" in result
        or "official_status" in result
        or "swebench_official_resolved" in metrics
        or "swebench_official_status" in metrics
    )


def _official_resolved(result: Mapping[str, Any], metrics: Mapping[str, Any]) -> Any:
    if "official_resolved" in result:
        return result.get("official_resolved")
    return metrics.get("swebench_official_resolved")


def _variant_results_table(variant_results: list[Any]) -> str:
    rows: list[tuple[Any, ...]] = []
    for item in variant_results:
        variant_result = _mapping(item)
        variant = _mapping(variant_result.get("variant"))
        summary = _mapping(variant_result.get("summary"))
        delta = _mapping(variant_result.get("delta_vs_baseline"))
        averages = _mapping(summary.get("metric_averages"))
        rows.append((
            variant.get("name"),
            _text(_mapping(variant_result.get("memory_policy")).get("policy")),
            _percent(summary.get("resolved_rate")),
            _percent(summary.get("first_pass_success_rate")),
            _percent(summary.get("retry_recovery_rate")),
            _number(averages.get("tool_calls")),
            _number(averages.get("patch_policy_changed_lines")),
            _number(averages.get("memory_hit_count")),
            _number(averages.get("memory_filtered_count")),
            _number(averages.get("memory_prompt_injected_count")),
            _signed_percent(delta.get("resolved_rate")),
            _signed_percent(delta.get("retry_recovery_rate")),
        ))
    return _markdown_table(
        [
            "Variant",
            "Memory Policy",
            "Resolved",
            "First Pass",
            "Retry Recovery",
            "Avg Tools",
            "Avg Patch Lines",
            "Memory Hits",
            "Memory Filtered",
            "Memory Injected",
            "Delta Resolved",
            "Delta Retry",
        ],
        rows,
    )


def _ablation_memory_policy(variant_results: list[Any]) -> str:
    policies = {
        _text(_mapping(_mapping(item).get("memory_policy")).get("policy"))
        for item in variant_results
    }
    policies.discard("")
    if not policies:
        return ""
    if len(policies) == 1:
        return next(iter(policies))
    return "mixed"


def _task_outcomes_table(task_outcomes: list[Any]) -> str:
    rows: list[tuple[Any, ...]] = []
    for item in task_outcomes:
        outcome = _mapping(item)
        rows.append((
            outcome.get("task_id"),
            _yes_no(outcome.get("baseline_resolved")),
            ", ".join(str(name) for name in _list(outcome.get("improved_variants"))),
            ", ".join(str(name) for name in _list(outcome.get("regressed_variants"))),
        ))
    return _markdown_table(
        ["Task", "Baseline", "Improved Variants", "Regressed Variants"],
        rows,
    )


def _markdown_table(headers: list[str], rows: list[tuple[Any, ...]]) -> str:
    if not rows:
        rows = [tuple("" for _ in headers)]
    rendered_rows = [
        [_escape_cell(_text(cell)) for cell in row]
        for row in rows
    ]
    rendered_headers = [_escape_cell(header) for header in headers]
    lines = [
        "| " + " | ".join(rendered_headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rendered_rows)
    return "\n".join(lines)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


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


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _number(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    if isinstance(value, int):
        return str(value)
    return ""


def _percent(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return ""
    return f"{value:.1%}"


def _signed_percent(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return ""
    return f"{value:+.1%}"


def _yes_no(value: Any) -> str:
    return "yes" if bool(value) else "no"


def _yes_no_optional(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    return ""


def _escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
