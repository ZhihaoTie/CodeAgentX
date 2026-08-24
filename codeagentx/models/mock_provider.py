"""Deterministic provider for offline tests and demos."""

from __future__ import annotations

from collections import deque
from typing import Any, Iterable

from .base import ContentBlock, ModelResponse


MockResponseInput = ModelResponse | str | list[ContentBlock]


class MockProvider:
    """A scriptable provider that never touches the network."""

    @property
    def name(self) -> str:
        return "mock"

    def __init__(self, responses: Iterable[MockResponseInput] | None = None) -> None:
        self._responses: deque[MockResponseInput] = deque(responses or [])
        self.requests: list[dict[str, Any]] = []

    def create_message(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> ModelResponse:
        self.requests.append({
            "model": model,
            "system": system,
            "messages": list(messages),
            "tools": list(tools),
            "max_tokens": max_tokens,
        })

        if not self._responses:
            return ModelResponse.text("Mock provider response.", model=model)

        response = self._responses.popleft()
        if isinstance(response, ModelResponse):
            return response
        if isinstance(response, str):
            return ModelResponse.text(response, model=model)
        return ModelResponse(content=list(response), model=model)
