"""Context management -- distilled from Claude Code's context system.

Original system includes:
  - Session persistence in ~/.claude/sessions/
  - Context compaction (summarizing old messages when nearing window limit)
  - CLAUDE.md loading for project-level instructions
  - Auto-memory across sessions
  - Transcript stores with flush/replay

Mini version:
  - In-memory message list
  - Simple truncation (drop oldest messages when over limit)
  - CLAUDE.md loading from project root
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Config


@dataclass
class Message:
    role: str  # "user", "assistant", "system"
    content: Any  # str or list of content blocks


@dataclass(frozen=True)
class ContextWindow:
    """Keeps a bounded, provider-valid slice of conversation messages."""

    max_messages: int

    def trim(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        limit = max(1, int(self.max_messages))
        if len(messages) <= limit:
            return list(messages)

        pinned = messages[:1]
        units = _message_units(messages[1:])
        budget = max(0, limit - len(pinned))
        selected: list[list[dict[str, Any]]] = []

        newest_unit = units[-1] if units else []
        if newest_unit and len(newest_unit) > budget:
            return pinned + list(newest_unit)

        for unit in reversed(units):
            unit_size = len(unit)
            if unit_size <= budget:
                selected.append(unit)
                budget -= unit_size

        selected.reverse()
        recent = [message for unit in selected for message in unit]

        # A tool exchange is atomic. If the configured window is too small to
        # hold the newest exchange beside the pinned task, keep that exchange
        # intact rather than sending an orphaned tool result.
        if not recent and newest_unit:
            recent = list(newest_unit)
        return pinned + recent


@dataclass
class ConversationContext:
    """Manages the conversation message history and system prompt."""

    config: Config
    messages: list[dict[str, Any]] = field(default_factory=list)
    _system_prompt: str = ""

    def set_system_prompt(self, prompt: str) -> None:
        self._system_prompt = prompt

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    def add_user_message(self, content: str) -> None:
        self._append({"role": "user", "content": content})

    def add_assistant_message(self, content: Any) -> None:
        self._append({"role": "assistant", "content": content})

    def add_tool_result(self, tool_use_id: str, content: str, is_error: bool = False) -> None:
        self.add_tool_results([{
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": content,
            "is_error": is_error,
        }])

    def add_tool_results(self, tool_results: list[dict[str, Any]]) -> None:
        self._append({
            "role": "user",
            "content": list(tool_results),
        })

    def _append(self, message: dict[str, Any]) -> None:
        self.messages.append(message)
        self._truncate_if_needed()

    def get_api_messages(self) -> list[dict[str, Any]]:
        return list(self.messages)

    def _truncate_if_needed(self) -> None:
        """Trim old messages without splitting a tool exchange."""
        window = ContextWindow(self.config.max_context_messages)
        self.messages = window.trim(self.messages)


def _message_units(messages: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    units: list[list[dict[str, Any]]] = []
    index = 0
    while index < len(messages):
        current = messages[index]
        if (
            _is_assistant_tool_message(current)
            and index + 1 < len(messages)
            and _is_tool_result_message(messages[index + 1])
        ):
            units.append([current, messages[index + 1]])
            index += 2
            continue
        units.append([current])
        index += 1
    return units


def _is_assistant_tool_message(message: dict[str, Any]) -> bool:
    if message.get("role") != "assistant":
        return False
    content = message.get("content")
    return isinstance(content, list) and any(
        isinstance(block, dict) and block.get("type") == "tool_use"
        for block in content
    )


def _is_tool_result_message(message: dict[str, Any]) -> bool:
    if message.get("role") != "user":
        return False
    content = message.get("content")
    return (
        isinstance(content, list)
        and bool(content)
        and all(
            isinstance(block, dict) and block.get("type") == "tool_result"
            for block in content
        )
    )


def load_project_instructions(project_dir: str | Path | None = None) -> str:
    """Load CLAUDE.md from the project root, similar to how Claude Code does it."""
    if project_dir is None:
        project_dir = Path.cwd()
    else:
        project_dir = Path(project_dir)

    claude_md = project_dir / "CLAUDE.md"
    if claude_md.exists():
        return claude_md.read_text(encoding="utf-8", errors="replace").strip()
    return ""
