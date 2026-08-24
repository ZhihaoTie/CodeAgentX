"""Model provider adapters."""

from __future__ import annotations

from typing import Any

from .anthropic_provider import AnthropicProvider
from .base import ContentBlock, ModelProvider, ModelResponse
from .deepseek_provider import DeepSeekProvider
from .mock_provider import MockProvider


def create_model_provider(config: Any) -> ModelProvider:
    provider_name = getattr(config, "model_provider", "anthropic").lower()
    if provider_name == "anthropic":
        return AnthropicProvider()
    if provider_name == "deepseek":
        return DeepSeekProvider(
            timeout_seconds=getattr(config, "api_timeout_seconds", 120.0),
            max_retries=getattr(config, "api_max_retries", 0),
            retry_backoff_seconds=getattr(config, "api_retry_backoff_seconds", 1.0),
        )
    if provider_name == "mock":
        return MockProvider()
    raise ValueError(f"Unsupported model provider: {provider_name}")


__all__ = [
    "AnthropicProvider",
    "ContentBlock",
    "DeepSeekProvider",
    "MockProvider",
    "ModelProvider",
    "ModelResponse",
    "create_model_provider",
]
