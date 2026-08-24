"""DeepSeek/OpenAI-compatible chat completions provider adapter."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from .base import ModelResponse


HttpPost = Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]]
RETRYABLE_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504}


class DeepSeekAPIError(RuntimeError):
    """HTTP error returned by the DeepSeek API."""

    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"DeepSeek API error {status_code}: {body}")


class DeepSeekProvider:
    """Adapter for DeepSeek's OpenAI-compatible chat completions API."""

    @property
    def name(self) -> str:
        return "deepseek"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        chat_path: str | None = None,
        timeout_seconds: float = 120.0,
        max_retries: int = 0,
        retry_backoff_seconds: float = 1.0,
        http_post: HttpPost | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("DEEPSEEK_API_KEY", "")
        self.base_url = (base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")).rstrip("/")
        self.chat_path = chat_path or os.getenv("DEEPSEEK_CHAT_PATH", "/chat/completions")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, max_retries)
        self.retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        self.http_post = http_post or _urllib_post_json

    def create_message(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> ModelResponse:
        if not self.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is not set")

        payload = {
            "model": model,
            "messages": _to_openai_messages(system, messages),
            "tools": _to_openai_tools(tools),
            "tool_choice": "auto",
            "max_tokens": max_tokens,
        }
        response = self._post_with_retries(
            self.base_url + self.chat_path,
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            payload,
        )
        return _to_model_response(response, fallback_model=model)

    def _post_with_retries(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return self.http_post(url, headers, payload, self.timeout_seconds)
            except Exception as exc:
                last_error = exc
                if attempt >= self.max_retries or not _is_retryable_error(exc):
                    raise
                delay = self.retry_backoff_seconds * (2 ** attempt)
                if delay > 0:
                    time.sleep(delay)
        assert last_error is not None
        raise last_error


def _to_openai_messages(system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    if system:
        converted.append({"role": "system", "content": system})

    for message in messages:
        role = str(message.get("role", "user"))
        content = message.get("content", "")
        if isinstance(content, str):
            converted.append({"role": role, "content": content})
            continue

        blocks = content if isinstance(content, list) else []
        if _is_tool_result_blocks(blocks):
            converted.extend(_to_tool_result_messages(blocks))
            continue
        if role == "assistant":
            converted.append(_to_assistant_message(blocks))
            continue

        text = "\n".join(
            str(block.get("text", block.get("content", "")))
            for block in blocks
            if isinstance(block, dict)
        )
        converted.append({"role": role, "content": text})

    return converted


def _to_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": str(tool.get("name", "")),
                "description": str(tool.get("description", "")),
                "parameters": tool.get("input_schema", {}),
            },
        }
        for tool in tools
    ]


def _to_model_response(response: dict[str, Any], *, fallback_model: str) -> ModelResponse:
    choices = response.get("choices", [])
    choice = choices[0] if choices else {}
    message = choice.get("message", {}) if isinstance(choice, dict) else {}
    content: list[dict[str, Any]] = []

    text = message.get("content", "")
    if text:
        content.append({"type": "text", "text": str(text)})

    for tool_call in message.get("tool_calls", []) or []:
        if not isinstance(tool_call, dict):
            continue
        function = tool_call.get("function", {})
        if not isinstance(function, dict):
            function = {}
        content.append({
            "type": "tool_use",
            "id": str(tool_call.get("id", "")),
            "name": str(function.get("name", "")),
            "input": _parse_arguments(function.get("arguments", "{}")),
        })

    return ModelResponse(
        content=content,
        model=str(response.get("model", fallback_model)),
        stop_reason=str(choice.get("finish_reason", "")) if isinstance(choice, dict) else "",
        usage=response.get("usage", {}) if isinstance(response.get("usage"), dict) else {},
        raw=response,
    )


def _to_assistant_message(blocks: list[Any]) -> dict[str, Any]:
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text = str(block.get("text", ""))
            if text:
                text_parts.append(text)
        elif block_type == "tool_use":
            tool_calls.append({
                "id": str(block.get("id", "")),
                "type": "function",
                "function": {
                    "name": str(block.get("name", "")),
                    "arguments": json.dumps(block.get("input", {}) or {}),
                },
            })

    message: dict[str, Any] = {
        "role": "assistant",
        "content": "\n".join(text_parts) if text_parts else None,
    }
    if tool_calls:
        message["tool_calls"] = tool_calls
    return message


def _to_tool_result_messages(blocks: list[Any]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            continue
        messages.append({
            "role": "tool",
            "tool_call_id": str(block.get("tool_use_id", "")),
            "content": str(block.get("content", "")),
        })
    return messages


def _is_tool_result_blocks(blocks: list[Any]) -> bool:
    return bool(blocks) and all(
        isinstance(block, dict) and block.get("type") == "tool_result"
        for block in blocks
    )


def _parse_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _urllib_post_json(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise DeepSeekAPIError(exc.code, body) from exc
    return json.loads(raw)


def _is_retryable_error(exc: Exception) -> bool:
    if isinstance(exc, DeepSeekAPIError):
        return exc.status_code in RETRYABLE_STATUS_CODES
    return isinstance(exc, (TimeoutError, urllib.error.URLError))
