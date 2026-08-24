"""Anthropic model provider adapter."""

from __future__ import annotations

from typing import Any

from .base import ModelResponse, normalize_content_blocks


class AnthropicProvider:
    """Thin adapter that hides Anthropic SDK objects from AgentLoop."""

    @property
    def name(self) -> str:
        return "anthropic"

    def __init__(self, client: Any | None = None) -> None:
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self.client = client

    def create_message(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> ModelResponse:
        response = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            tools=tools,
            messages=messages,
        )
        return ModelResponse(
            content=normalize_content_blocks(response.content),
            model=getattr(response, "model", model),
            stop_reason=getattr(response, "stop_reason", ""),
            usage=_usage_to_dict(getattr(response, "usage", None)),
            raw=response,
        )


def _usage_to_dict(usage: Any) -> dict[str, Any]:
    if usage is None:
        return {}

    result: dict[str, Any] = {}
    for key in (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    ):
        value = getattr(usage, key, None)
        if value is not None:
            result[key] = value
    return result
