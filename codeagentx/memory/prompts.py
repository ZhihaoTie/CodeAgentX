"""Prompt rendering for retrieved memory."""

from __future__ import annotations

from typing import Any, Mapping


def format_memory_prompt(
    report: Mapping[str, Any],
    *,
    max_chars: int = 2_500,
    limit: int = 3,
) -> str:
    """Render retrieved memories as bounded, source-aware guidance."""

    hits = report.get("hits", []) if isinstance(report, Mapping) else []
    if not isinstance(hits, list) or not hits:
        return ""

    lines = [
        "Relevant verified memories from previous successful tasks:",
    ]
    for index, hit in enumerate(hits[:limit], start=1):
        if not isinstance(hit, Mapping):
            continue
        record = hit.get("memory", {})
        if not isinstance(record, Mapping):
            continue
        lines.append(
            f"{index}. {record.get('task_type', 'software_task')} "
            f"({record.get('language', 'unknown')}) [score={hit.get('score', 0)}]"
        )
        if record.get("source_goal"):
            lines.append(f"   Prior task: {record.get('source_goal')}")
        if record.get("symptoms"):
            lines.append("   Symptoms: " + "; ".join(str(item) for item in record["symptoms"][:4]))
        if record.get("root_cause"):
            lines.append(f"   Root cause: {record.get('root_cause')}")
        if record.get("strategy"):
            lines.append(f"   Successful strategy: {record.get('strategy')}")
        if record.get("changed_files"):
            lines.append("   Changed files: " + ", ".join(str(item) for item in record["changed_files"][:5]))
        if record.get("applicability"):
            lines.append(f"   Applicability: {record.get('applicability')}")
        if record.get("evidence_path"):
            lines.append(f"   Evidence: {record.get('evidence_path')}")
        reasons = hit.get("reasons", [])
        if isinstance(reasons, list) and reasons:
            lines.append("   Retrieval reasons: " + "; ".join(str(item) for item in reasons[:4]))

    lines.append(
        "Use these memories as hypotheses only. Prefer current repository evidence "
        "when it conflicts with a memory."
    )
    return _truncate("\n".join(lines), max_chars)


def _truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    omitted = len(value) - max_chars
    return value[:max_chars] + f"\n... memory prompt truncated {omitted} chars"
