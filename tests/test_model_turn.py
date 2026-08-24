"""Tests for model-turn orchestration."""

from __future__ import annotations

import unittest
from io import StringIO

from codeagentx.agent import ModelTurnController
from codeagentx.config import Config
from codeagentx.context import ConversationContext
from codeagentx.models import MockProvider, ModelResponse
from codeagentx.tools.base import ToolRegistry
from codeagentx.tools.glob_tool import GlobTool


class ModelTurnControllerTests(unittest.TestCase):
    def test_run_turn_calls_provider_parses_response_and_records_assistant_message(self):
        provider = MockProvider([
            ModelResponse.tool_use(
                tool_use_id="toolu_1",
                name="glob",
                tool_input={"pattern": "*.py"},
                text="I will inspect.",
                model="mock-model",
            )
        ])
        config = Config(model_provider="mock", model="mock-model")
        context = ConversationContext(config=config)
        context.set_system_prompt("system")
        context.add_user_message("inspect")
        registry = ToolRegistry()
        registry.register(GlobTool())
        output = StringIO()
        controller = ModelTurnController(
            config=config,
            context=context,
            provider=provider,
            registry=registry,
            output=output,
        )

        turn = controller.run_turn()

        self.assertEqual(turn.final_text, "I will inspect.")
        self.assertTrue(turn.has_tool_calls)
        self.assertEqual(turn.tool_calls[0]["id"], "toolu_1")
        self.assertEqual(turn.tool_calls[0]["name"], "glob")
        self.assertEqual(provider.requests[0]["system"], "system")
        self.assertEqual(provider.requests[0]["messages"][0]["content"], "inspect")
        self.assertEqual(context.messages[-1]["role"], "assistant")
        self.assertIn("I will inspect.", output.getvalue())
        self.assertIn("[Tool: glob]", output.getvalue())

    def test_parse_response_handles_text_only_final_turn(self):
        config = Config(model_provider="mock", model="mock-model")
        controller = ModelTurnController(
            config=config,
            context=ConversationContext(config=config),
            provider=MockProvider(),
            registry=ToolRegistry(),
            output=StringIO(),
        )

        turn = controller.parse_response(ModelResponse.text("Done.", model="mock-model"))

        self.assertEqual(turn.final_text, "Done.")
        self.assertFalse(turn.has_tool_calls)
        self.assertEqual(turn.tool_calls, [])


if __name__ == "__main__":
    unittest.main()
