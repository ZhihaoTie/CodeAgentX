"""Model-turn orchestration for CodeAgent-X."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any, TextIO

from codeagentx.config import Config
from codeagentx.context import ConversationContext
from codeagentx.models import ModelProvider, ModelResponse
from codeagentx.terminal import write_text
from codeagentx.tools.base import ToolRegistry


@dataclass(frozen=True)
class ModelTurn:
    """Normalized model response data used by the agent loop."""

    response: ModelResponse
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    text_parts: list[str] = field(default_factory=list)

    @property
    def final_text(self) -> str:
        return "\n".join(self.text_parts)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


class ModelTurnController:
    """Calls the model provider and normalizes one model turn."""

    def __init__(
        self,
        *,
        config: Config,
        context: ConversationContext,
        provider: ModelProvider,
        registry: ToolRegistry,
        output: TextIO | None = None,
    ) -> None:
        self.config = config
        self.context = context
        self.provider = provider
        self.registry = registry
        self.output = output

    def run_turn(self) -> ModelTurn:
        response = self.call_api()
        turn = self.parse_response(response)
        self.context.add_assistant_message(response.content)
        return turn

    def call_api(self) -> ModelResponse:
        return self.provider.create_message(
            model=self.config.model,
            system=self.context.system_prompt,
            tools=self.registry.api_schemas(),
            messages=self.context.get_api_messages(),
            max_tokens=self.config.max_tokens,
        )

    def parse_response(self, response: ModelResponse) -> ModelTurn:
        tool_calls: list[dict[str, Any]] = []
        text_parts: list[str] = []

        for block in response.content:
            block_type = _block_value(block, "type")
            if block_type == "text":
                text = str(_block_value(block, "text") or "")
                text_parts.append(text)
                self._write(text)
            elif block_type == "tool_use":
                tool_input = _block_value(block, "input") or {}
                tool_calls.append({
                    "id": _block_value(block, "id"),
                    "name": _block_value(block, "name"),
                    "input": tool_input,
                })
                input_preview = str(tool_input)
                if len(input_preview) > 120:
                    input_preview = input_preview[:120] + "..."
                self._write(f"\n[Tool: {_block_value(block, 'name')}] {input_preview}\n")

        return ModelTurn(
            response=response,
            tool_calls=tool_calls,
            text_parts=text_parts,
        )

    def _write(self, text: str) -> None:
        output = self.output if self.output is not None else sys.stdout
        write_text(text, output)


def _block_value(block: Any, key: str) -> Any:
    if isinstance(block, dict):
        return block.get(key)
    return getattr(block, key, None)
