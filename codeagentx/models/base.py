"""Provider-neutral model response types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


ContentBlock = dict[str, Any]


@dataclass(frozen=True)
class ModelResponse:
    """A provider-neutral response consumed by AgentLoop."""

    content: list[ContentBlock]
    model: str = ""
    stop_reason: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    raw: Any = field(default=None, repr=False, compare=False)

    @classmethod
    def text(cls, text: str, *, model: str = "mock") -> "ModelResponse":
        return cls(content=[{"type": "text", "text": text}], model=model)

    @classmethod
    def tool_use(
        cls,
        *,
        tool_use_id: str,
        name: str,
        tool_input: dict[str, Any],
        text: str = "",
        model: str = "mock",
    ) -> "ModelResponse":
        content: list[ContentBlock] = []
        if text:
            content.append({"type": "text", "text": text})
        content.append({
            "type": "tool_use",
            "id": tool_use_id,
            "name": name,
            "input": tool_input,
        })
        return cls(content=content, model=model, stop_reason="tool_use")

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "model": self.model,
            "stop_reason": self.stop_reason,
            "usage": dict(self.usage),
        }


class ModelProvider(Protocol):
    """Protocol implemented by concrete LLM provider adapters."""

    @property
    def name(self) -> str: ...

    def create_message(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> ModelResponse: ...


def normalize_content_blocks(content: Any) -> list[ContentBlock]:
    """Convert provider SDK content blocks into plain JSON-like dicts."""
    normalized: list[ContentBlock] = []
    for block in content:
        if isinstance(block, dict):
            normalized.append(dict(block))
            continue

        block_type = getattr(block, "type", "")
        if block_type == "text":
            normalized.append({
                "type": "text",
                "text": getattr(block, "text", ""),
            })
        elif block_type == "tool_use":
            normalized.append({
                "type": "tool_use",
                "id": getattr(block, "id", ""),
                "name": getattr(block, "name", ""),
                "input": getattr(block, "input", {}),
            })
        else:
            normalized.append({
                "type": block_type or "unknown",
                "repr": repr(block),
            })
    return normalized
