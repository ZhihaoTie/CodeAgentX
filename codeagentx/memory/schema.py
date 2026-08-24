"""Schema objects for durable agent memory."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from codeagentx.agent.state import utc_now_iso


MEMORY_SCHEMA_VERSION = "codeagentx.memory.v1"


@dataclass(frozen=True)
class MemoryRecord:
    """A verified repair experience extracted from a successful trajectory."""

    memory_id: str
    task_id: str
    task_type: str
    language: str
    source_goal: str
    symptoms: list[str] = field(default_factory=list)
    root_cause: str = ""
    strategy: str = ""
    changed_files: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    evidence_path: str = ""
    applicability: str = ""
    verified: bool = True
    created_at: str = field(default_factory=utc_now_iso)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": MEMORY_SCHEMA_VERSION,
            "memory_id": self.memory_id,
            "task_id": self.task_id,
            "task_type": self.task_type,
            "language": self.language,
            "source_goal": self.source_goal,
            "symptoms": list(self.symptoms),
            "root_cause": self.root_cause,
            "strategy": self.strategy,
            "changed_files": list(self.changed_files),
            "tests": list(self.tests),
            "evidence_path": self.evidence_path,
            "applicability": self.applicability,
            "verified": self.verified,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MemoryRecord":
        return cls(
            memory_id=str(payload.get("memory_id", "")),
            task_id=str(payload.get("task_id", "")),
            task_type=str(payload.get("task_type", "software_task") or "software_task"),
            language=str(payload.get("language", "unknown") or "unknown"),
            source_goal=str(payload.get("source_goal", "") or ""),
            symptoms=_string_list(payload.get("symptoms")),
            root_cause=str(payload.get("root_cause", "") or ""),
            strategy=str(payload.get("strategy", "") or ""),
            changed_files=_string_list(payload.get("changed_files")),
            tests=_string_list(payload.get("tests")),
            evidence_path=str(payload.get("evidence_path", "") or ""),
            applicability=str(payload.get("applicability", "") or ""),
            verified=bool(payload.get("verified", True)),
            created_at=str(payload.get("created_at", "") or utc_now_iso()),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class MemorySearchHit:
    """A retrieved memory with ranking evidence."""

    record: MemoryRecord
    score: int
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory": self.record.to_dict(),
            "score": self.score,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class MemoryRetrievalReport:
    """Auditable top-K memory retrieval result."""

    status: str
    summary: str
    query_terms: list[str] = field(default_factory=list)
    hits: list[MemorySearchHit] = field(default_factory=list)
    candidate_count: int = 0
    filtered_hit_count: int = 0
    min_score: int = 0
    top_candidate_score: int | None = None
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "query_terms": list(self.query_terms),
            "hits": [hit.to_dict() for hit in self.hits],
            "candidate_count": self.candidate_count,
            "filtered_hit_count": self.filtered_hit_count,
            "min_score": self.min_score,
            "top_candidate_score": self.top_candidate_score,
            "created_at": self.created_at,
        }


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    return [str(item) for item in value if str(item)]
