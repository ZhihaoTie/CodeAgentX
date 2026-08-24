"""Retrieve task-relevant long-term memories."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from .schema import MemoryRecord, MemoryRetrievalReport, MemorySearchHit
from .store import MemoryStore


STOPWORDS = {
    "after",
    "agent",
    "all",
    "and",
    "any",
    "are",
    "before",
    "been",
    "being",
    "both",
    "code",
    "current",
    "did",
    "does",
    "documented",
    "edit",
    "done",
    "error",
    "existing",
    "failed",
    "failure",
    "file",
    "fix",
    "for",
    "from",
    "function",
    "has",
    "have",
    "having",
    "into",
    "its",
    "issue",
    "keep",
    "make",
    "method",
    "model",
    "new",
    "not",
    "only",
    "other",
    "out",
    "patch",
    "present",
    "provided",
    "requested",
    "report",
    "return",
    "returns",
    "retry",
    "run",
    "should",
    "than",
    "task",
    "test",
    "tests",
    "that",
    "the",
    "their",
    "this",
    "tool",
    "unchanged",
    "verification",
    "when",
    "where",
    "while",
    "whose",
    "with",
    "without",
}


class MemoryRetriever:
    """Keyword scorer for verified memory records."""

    def __init__(
        self,
        store: MemoryStore,
        *,
        default_limit: int = 3,
        default_min_score: int = 0,
    ) -> None:
        self.store = store
        self.default_limit = default_limit
        self.default_min_score = max(0, int(default_min_score))

    def retrieve(
        self,
        *,
        goal: str,
        reflection_report: Mapping[str, Any] | None = None,
        patches: Iterable[Mapping[str, Any]] | None = None,
        limit: int | None = None,
        min_score: int | None = None,
    ) -> MemoryRetrievalReport:
        records = [record for record in self.store.list_records() if record.verified]
        query_terms = _query_terms(goal, reflection_report, patches)
        threshold = max(
            0,
            int(self.default_min_score if min_score is None else min_score),
        )
        if not records:
            return MemoryRetrievalReport(
                status="empty_store",
                summary="No verified long-term memories are available.",
                query_terms=query_terms,
                min_score=threshold,
            )

        hits = [
            hit
            for record in records
            if (hit := _score_record(record, query_terms))
            if hit.score > 0
        ]
        hits.sort(key=lambda item: (-item.score, item.record.created_at, item.record.memory_id))
        selected_candidates = [hit for hit in hits if hit.score >= threshold]
        selected = selected_candidates[: int(limit or self.default_limit or 3)]
        filtered_count = len(hits) - len(selected_candidates)
        top_candidate_score = hits[0].score if hits else None
        if selected:
            status = "generated"
            summary = (
                f"Retrieved {len(selected)} verified memory hit(s) "
                f"from {len(records)} stored record(s)."
            )
        elif hits:
            status = "filtered"
            summary = (
                f"Skipped memory injection: top score {top_candidate_score} "
                f"is below min_score {threshold}."
            )
        else:
            status = "empty"
            summary = (
                f"No candidate memories matched query terms across {len(records)} "
                "stored record(s)."
            )
        return MemoryRetrievalReport(
            status=status,
            summary=summary,
            query_terms=query_terms,
            hits=selected,
            candidate_count=len(hits),
            filtered_hit_count=filtered_count,
            min_score=threshold,
            top_candidate_score=top_candidate_score,
        )


def _score_record(record: MemoryRecord, query_terms: list[str]) -> MemorySearchHit:
    record_terms = _record_terms(record)
    score = 0
    reasons: list[str] = []

    for term in query_terms:
        if term not in record_terms:
            continue
        weight = record_terms[term]
        score += weight
        if len(reasons) < 6:
            reasons.append(f'matched "{term}"')

    if record.language != "unknown" and record.language in query_terms:
        score += 20
        reasons.append(f"language match: {record.language}")

    return MemorySearchHit(record=record, score=score, reasons=_unique(reasons))


def _record_terms(record: MemoryRecord) -> dict[str, int]:
    weighted: dict[str, int] = {}
    for value, weight in [
        (record.source_goal, 10),
        (record.task_type, 12),
        (record.language, 14),
        (record.root_cause, 8),
        (record.strategy, 8),
        (record.applicability, 8),
    ]:
        _add_terms(weighted, _tokens(value), weight)
    for value in record.symptoms:
        _add_terms(weighted, _tokens(value), 14)
    for value in record.changed_files:
        _add_terms(weighted, _tokens(value), 18)
        _add_terms(weighted, _tokens(Path(value).stem), 18)
    for value in record.tests:
        _add_terms(weighted, _tokens(value), 16)
    return weighted


def _query_terms(
    goal: str,
    reflection_report: Mapping[str, Any] | None,
    patches: Iterable[Mapping[str, Any]] | None,
) -> list[str]:
    terms = _tokens(goal)
    if isinstance(reflection_report, Mapping):
        terms.extend(_tokens(reflection_report.get("summary", "")))
        for signal in reflection_report.get("signals", []) or []:
            if not isinstance(signal, Mapping):
                continue
            terms.extend(_tokens(signal.get("category", "")))
            terms.extend(_tokens(signal.get("message", "")))
            evidence = signal.get("evidence", {})
            if isinstance(evidence, Mapping):
                for value in evidence.values():
                    terms.extend(_tokens(value))
    for patch in patches or []:
        if not isinstance(patch, Mapping):
            continue
        path = patch.get("path")
        if path:
            terms.extend(_tokens(str(path)))
            terms.extend(_tokens(Path(str(path)).stem))
    return _unique([term for term in terms if term not in STOPWORDS])[:24]


def _add_terms(target: dict[str, int], terms: Iterable[str], weight: int) -> None:
    for term in terms:
        target[term] = target.get(term, 0) + weight


def _tokens(value: Any) -> list[str]:
    text = str(value or "")
    tokens: list[str] = []
    for raw in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text):
        lowered = raw.lower()
        tokens.append(lowered)
        tokens.extend(part for part in lowered.split("_") if len(part) >= 3)
        tokens.extend(_camel_parts(raw))
    return _unique(tokens)


def _camel_parts(value: str) -> list[str]:
    parts = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)", value)
    return [part.lower() for part in parts if len(part) >= 3]


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value).strip().lower()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
