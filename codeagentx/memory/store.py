"""JSONL-backed durable memory store."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Mapping

from .schema import MemoryRecord


class MemoryStore:
    """Append-only JSONL store for verified memory records."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()

    def list_records(self) -> list[MemoryRecord]:
        if not self.path.exists():
            return []

        records: list[MemoryRecord] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, Mapping):
                records.append(MemoryRecord.from_dict(payload))
        return records

    def append(self, record: MemoryRecord) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        return self.path

    def append_if_new(self, record: MemoryRecord) -> tuple[bool, Path | None]:
        if record.memory_id in {item.memory_id for item in self.list_records()}:
            return False, self.path if self.path.exists() else None
        return True, self.append(record)

    def extend_new(self, records: Iterable[MemoryRecord]) -> int:
        written = 0
        for record in records:
            added, _path = self.append_if_new(record)
            if added:
                written += 1
        return written
