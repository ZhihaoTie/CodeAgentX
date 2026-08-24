"""Rank task-relevant repository context from structured evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from codeagentx.agent.state import utc_now_iso

from .ast_index import AstContextManager, RepositoryAstIndex, SymbolSearchResult


STOPWORDS = {
    "after",
    "agent",
    "before",
    "code",
    "done",
    "error",
    "failed",
    "failure",
    "file",
    "fix",
    "from",
    "function",
    "issue",
    "make",
    "method",
    "model",
    "patch",
    "report",
    "retry",
    "run",
    "task",
    "test",
    "tests",
    "that",
    "this",
    "tool",
    "verification",
    "with",
}


@dataclass(frozen=True)
class ContextCandidate:
    path: str
    line: int
    end_line: int
    score: int
    sources: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    symbol_name: str = ""
    kind: str = ""
    snippet: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "line": self.line,
            "end_line": self.end_line,
            "score": self.score,
            "sources": list(self.sources),
            "reasons": list(self.reasons),
            "symbol_name": self.symbol_name,
            "kind": self.kind,
            "snippet": self.snippet,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class RankedContextReport:
    status: str
    summary: str
    root: str
    query_terms: list[str] = field(default_factory=list)
    failed_tests: list[str] = field(default_factory=list)
    patch_paths: list[str] = field(default_factory=list)
    candidates: list[ContextCandidate] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "root": self.root,
            "query_terms": list(self.query_terms),
            "failed_tests": list(self.failed_tests),
            "patch_paths": list(self.patch_paths),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "created_at": self.created_at,
        }

    def format_block(self, *, limit: int | None = None) -> str:
        candidates = self.candidates if limit is None else self.candidates[:limit]
        lines = [
            "Ranked context:",
            self.summary,
        ]
        if not candidates:
            lines.append("- no ranked context candidates")
            return "\n".join(lines)

        for candidate in candidates:
            sources = ",".join(candidate.sources)
            label = candidate.symbol_name or candidate.kind or "context"
            lines.append(
                f"- {candidate.path}:{candidate.line} {label} "
                f"[score={candidate.score}; sources={sources}]"
            )
            if candidate.reasons:
                lines.append(f"  reasons: {'; '.join(candidate.reasons[:4])}")
            if candidate.snippet:
                lines.append(f"  snippet: {candidate.snippet}")
        return "\n".join(lines)


class ContextRanker:
    """Rank AST and text context using task and failure evidence."""

    def __init__(
        self,
        root: str | Path,
        *,
        max_files: int = 1_000,
        max_terms: int = 16,
        max_text_hits_per_term: int = 5,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.max_files = max_files
        self.max_terms = max_terms
        self.max_text_hits_per_term = max_text_hits_per_term

    @classmethod
    def from_config(cls, config: Any) -> "ContextRanker":
        return cls(
            getattr(config, "workspace_root", "."),
            max_files=getattr(config, "context_ranking_max_files", 1_000),
            max_terms=getattr(config, "context_ranking_max_terms", 16),
            max_text_hits_per_term=getattr(config, "context_ranking_max_text_hits_per_term", 5),
        )

    def rank(
        self,
        *,
        goal: str,
        reflection_report: Mapping[str, Any] | None = None,
        patches: Iterable[Mapping[str, Any]] | None = None,
        failed_tests: Iterable[str] | None = None,
        limit: int = 8,
    ) -> RankedContextReport:
        patch_paths = _patch_paths(patches or [])
        failure_names = _failed_tests(reflection_report, failed_tests)
        terms = _query_terms(
            goal=goal,
            reflection_report=reflection_report,
            failed_tests=failure_names,
            patch_paths=patch_paths,
            limit=self.max_terms,
        )

        index = AstContextManager(self.root, max_files=self.max_files).index
        accumulator: dict[tuple[str, int, str], _MutableCandidate] = {}

        for path in patch_paths:
            _add_candidate(
                accumulator,
                path=path,
                line=1,
                end_line=1,
                score=85,
                source="recent_patch",
                reason="file was modified in the current trajectory",
                kind="file",
            )

        for name in failure_names:
            path = _path_from_failed_test(name)
            if path:
                _add_candidate(
                    accumulator,
                    path=path,
                    line=1,
                    end_line=1,
                    score=90,
                    source="failed_test",
                    reason=f"failed test path {name}",
                    kind="test",
                )

        for term in terms:
            ast_weight = 2 if term in _terms_from_failed_tests(failure_names) else 1
            for result in index.find_symbols(term, limit=8):
                _add_ast_candidate(
                    accumulator,
                    result,
                    term=term,
                    score=max(25, result.score * ast_weight),
                )

        text_terms = terms[:]
        for term in text_terms:
            boost = 35 if term in _terms_from_failed_tests(failure_names) else 20
            for path, line, snippet in _text_hits(index, self.root, term, self.max_text_hits_per_term):
                _add_candidate(
                    accumulator,
                    path=path,
                    line=line,
                    end_line=line,
                    score=boost,
                    source="text",
                    reason=f'text contains "{term}"',
                    kind="line",
                    snippet=snippet,
                )

        candidates = [
            item.to_candidate()
            for item in accumulator.values()
        ]
        candidates = sorted(
            candidates,
            key=lambda item: (-item.score, item.path, item.line, item.symbol_name),
        )[:limit]

        status = "generated" if candidates else "empty"
        return RankedContextReport(
            status=status,
            summary=(
                f"Ranked {len(candidates)} context candidate(s) "
                f"from {len(terms)} query term(s)."
            ),
            root=str(self.root),
            query_terms=terms,
            failed_tests=failure_names,
            patch_paths=patch_paths,
            candidates=candidates,
        )


@dataclass
class _MutableCandidate:
    path: str
    line: int
    end_line: int
    score: int = 0
    sources: set[str] = field(default_factory=set)
    reasons: list[str] = field(default_factory=list)
    symbol_name: str = ""
    kind: str = ""
    snippet: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_candidate(self) -> ContextCandidate:
        return ContextCandidate(
            path=self.path,
            line=self.line,
            end_line=self.end_line,
            score=self.score,
            sources=sorted(self.sources),
            reasons=list(self.reasons),
            symbol_name=self.symbol_name,
            kind=self.kind,
            snippet=self.snippet,
            metadata=dict(self.metadata),
        )


def _add_ast_candidate(
    accumulator: dict[tuple[str, int, str], _MutableCandidate],
    result: SymbolSearchResult,
    *,
    term: str,
    score: int,
) -> None:
    symbol = result.symbol
    _add_candidate(
        accumulator,
        path=symbol.location.path,
        line=symbol.location.line,
        end_line=symbol.location.end_line,
        score=score,
        source="ast",
        reason=f'AST match "{term}": {", ".join(result.reasons)}',
        symbol_name=symbol.qualified_name,
        kind=symbol.kind.value,
        snippet=symbol.signature,
        metadata={"ast_score": result.score},
    )


def _add_candidate(
    accumulator: dict[tuple[str, int, str], _MutableCandidate],
    *,
    path: str,
    line: int,
    end_line: int,
    score: int,
    source: str,
    reason: str,
    symbol_name: str = "",
    kind: str = "",
    snippet: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> None:
    key = (path, int(line), symbol_name or kind)
    candidate = accumulator.get(key)
    if candidate is None:
        candidate = _MutableCandidate(
            path=path,
            line=int(line),
            end_line=int(end_line),
            symbol_name=symbol_name,
            kind=kind,
            snippet=snippet,
        )
        accumulator[key] = candidate

    candidate.score += int(score)
    candidate.sources.add(source)
    if reason and reason not in candidate.reasons:
        candidate.reasons.append(reason)
    if snippet and not candidate.snippet:
        candidate.snippet = snippet
    if metadata:
        candidate.metadata.update(dict(metadata))


def _query_terms(
    *,
    goal: str,
    reflection_report: Mapping[str, Any] | None,
    failed_tests: list[str],
    patch_paths: list[str],
    limit: int,
) -> list[str]:
    terms: list[str] = []
    terms.extend(_tokens(goal))
    terms.extend(_terms_from_failed_tests(failed_tests))

    if isinstance(reflection_report, Mapping):
        for signal in reflection_report.get("signals", []):
            if not isinstance(signal, Mapping):
                continue
            terms.extend(_tokens(signal.get("category", "")))
            terms.extend(_tokens(signal.get("message", "")))
            evidence = signal.get("evidence", {})
            if isinstance(evidence, Mapping):
                terms.extend(_terms_from_evidence(evidence))

    for path in patch_paths:
        terms.extend(_tokens(Path(path).stem))

    return _unique([term for term in terms if term not in STOPWORDS])[:limit]


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


def _failed_tests(
    reflection_report: Mapping[str, Any] | None,
    explicit: Iterable[str] | None,
) -> list[str]:
    names: list[str] = [str(item) for item in explicit or [] if str(item)]
    if isinstance(reflection_report, Mapping):
        for signal in reflection_report.get("signals", []):
            if not isinstance(signal, Mapping):
                continue
            evidence = signal.get("evidence", {})
            if not isinstance(evidence, Mapping):
                continue
            for name in evidence.get("failure_names", []) or []:
                if str(name):
                    names.append(str(name))
    return _unique(names)


def _terms_from_failed_tests(names: Iterable[str]) -> list[str]:
    terms: list[str] = []
    for name in names:
        terms.extend(_tokens(name))
        tail = str(name).split("::")[-1]
        terms.extend(_tokens(tail))
    return _unique([term for term in terms if term not in STOPWORDS])


def _terms_from_evidence(evidence: Mapping[str, Any]) -> list[str]:
    terms: list[str] = []
    for key in ("framework", "failure_names", "violations"):
        value = evidence.get(key)
        if isinstance(value, list):
            for item in value:
                terms.extend(_tokens(item))
        else:
            terms.extend(_tokens(value))
    return terms


def _patch_paths(patches: Iterable[Mapping[str, Any]]) -> list[str]:
    paths = [
        str(patch.get("path", "")).replace("\\", "/")
        for patch in patches
        if patch.get("path")
    ]
    return _unique(paths)


def _path_from_failed_test(name: str) -> str:
    prefix = str(name).split("::", 1)[0].replace("\\", "/")
    if prefix.endswith(".py"):
        return prefix
    return ""


def _text_hits(
    index: RepositoryAstIndex,
    root: Path,
    term: str,
    max_hits: int,
) -> list[tuple[str, int, str]]:
    hits: list[tuple[str, int, str]] = []
    lowered = term.lower()
    for file_index in index.files:
        if file_index.parse_error:
            continue
        path = root / file_index.path
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line_number, line in enumerate(lines, start=1):
            if lowered not in line.lower():
                continue
            hits.append((file_index.path, line_number, line.strip()[:180]))
            if len(hits) >= max_hits:
                return hits
    return hits


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
