"""Tests for model provider abstraction and trajectory persistence."""

from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from codeagentx.agent import AgentLoop, AgentState
from codeagentx.config import Config, PermissionMode
from codeagentx.models import AnthropicProvider, DeepSeekProvider, MockProvider, ModelResponse, create_model_provider
from codeagentx.models.deepseek_provider import DeepSeekAPIError
from codeagentx.storage import SCHEMA_VERSION, TrajectoryStore


class TestMockProvider(unittest.TestCase):
    def test_returns_scripted_responses_and_records_requests(self):
        provider = MockProvider(["hello", ModelResponse.text("done", model="mock-model")])

        first = provider.create_message(
            model="mock-model",
            system="system",
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
            max_tokens=128,
        )
        second = provider.create_message(
            model="mock-model",
            system="system",
            messages=[],
            tools=[],
            max_tokens=128,
        )

        self.assertEqual(first.content[0]["text"], "hello")
        self.assertEqual(second.content[0]["text"], "done")
        self.assertEqual(len(provider.requests), 2)
        self.assertEqual(provider.requests[0]["model"], "mock-model")


class TestAnthropicProvider(unittest.TestCase):
    def test_normalizes_sdk_response(self):
        class FakeMessages:
            def create(self, **kwargs):
                self.kwargs = kwargs
                return SimpleNamespace(
                    content=[
                        SimpleNamespace(type="text", text="checking"),
                        SimpleNamespace(
                            type="tool_use",
                            id="toolu_1",
                            name="glob",
                            input={"pattern": "*.py"},
                        ),
                    ],
                    model="claude-test",
                    stop_reason="tool_use",
                    usage=SimpleNamespace(input_tokens=7, output_tokens=11),
                )

        fake_messages = FakeMessages()
        provider = AnthropicProvider(client=SimpleNamespace(messages=fake_messages))

        response = provider.create_message(
            model="claude-test",
            system="system",
            messages=[],
            tools=[],
            max_tokens=256,
        )

        self.assertEqual(fake_messages.kwargs["max_tokens"], 256)
        self.assertEqual(response.content[0]["text"], "checking")
        self.assertEqual(response.content[1]["name"], "glob")
        self.assertEqual(response.usage["input_tokens"], 7)


class TestDeepSeekProvider(unittest.TestCase):
    def test_converts_openai_tool_calls_to_model_response(self):
        captured = {}

        def fake_post(url, headers, payload, timeout_seconds):
            captured["url"] = url
            captured["headers"] = headers
            captured["payload"] = payload
            captured["timeout_seconds"] = timeout_seconds
            return {
                "model": "deepseek-v4-pro",
                "choices": [{
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": "I will inspect files.",
                        "tool_calls": [{
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "glob",
                                "arguments": '{"pattern": "*.py"}',
                            },
                        }],
                    },
                }],
                "usage": {"prompt_tokens": 9, "completion_tokens": 4},
            }

        provider = DeepSeekProvider(
            api_key="test-key",
            base_url="https://example.test",
            timeout_seconds=42,
            http_post=fake_post,
        )

        response = provider.create_message(
            model="deepseek-v4-pro",
            system="system prompt",
            messages=[
                {"role": "user", "content": "inspect"},
                {
                    "role": "assistant",
                    "content": [{
                        "type": "tool_use",
                        "id": "call_previous",
                        "name": "read_file",
                        "input": {"path": "README.md"},
                    }],
                },
                {
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": "call_previous",
                        "content": "README",
                        "is_error": False,
                    }],
                },
            ],
            tools=[{
                "name": "glob",
                "description": "Find files",
                "input_schema": {
                    "type": "object",
                    "properties": {"pattern": {"type": "string"}},
                },
            }],
            max_tokens=128,
        )

        self.assertEqual(captured["url"], "https://example.test/chat/completions")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(captured["timeout_seconds"], 42)
        self.assertEqual(captured["payload"]["model"], "deepseek-v4-pro")
        self.assertEqual(captured["payload"]["messages"][0]["role"], "system")
        self.assertEqual(captured["payload"]["messages"][2]["tool_calls"][0]["function"]["name"], "read_file")
        self.assertEqual(captured["payload"]["messages"][3]["role"], "tool")
        self.assertEqual(captured["payload"]["tools"][0]["function"]["name"], "glob")
        self.assertEqual(response.content[0]["text"], "I will inspect files.")
        self.assertEqual(response.content[1]["type"], "tool_use")
        self.assertEqual(response.content[1]["name"], "glob")
        self.assertEqual(response.content[1]["input"], {"pattern": "*.py"})
        self.assertEqual(response.usage["prompt_tokens"], 9)

    def test_missing_api_key_is_clear_error(self):
        provider = DeepSeekProvider(api_key="", http_post=lambda url, headers, payload, timeout: {})

        with self.assertRaisesRegex(RuntimeError, "DEEPSEEK_API_KEY"):
            provider.create_message(
                model="deepseek-v4-pro",
                system="",
                messages=[],
                tools=[],
                max_tokens=128,
            )

    def test_create_model_provider_supports_deepseek(self):
        provider = create_model_provider(Config(
            model_provider="deepseek",
            api_timeout_seconds=33,
            api_max_retries=2,
            api_retry_backoff_seconds=0,
        ))

        self.assertIsInstance(provider, DeepSeekProvider)
        self.assertEqual(provider.timeout_seconds, 33)
        self.assertEqual(provider.max_retries, 2)

    def test_retries_retryable_deepseek_errors(self):
        calls = []

        def flaky_post(url, headers, payload, timeout_seconds):
            calls.append(timeout_seconds)
            if len(calls) == 1:
                raise DeepSeekAPIError(429, "rate limit")
            return {
                "model": "deepseek-v4-pro",
                "choices": [{
                    "finish_reason": "stop",
                    "message": {"content": "Recovered."},
                }],
            }

        provider = DeepSeekProvider(
            api_key="test-key",
            max_retries=1,
            retry_backoff_seconds=0,
            timeout_seconds=9,
            http_post=flaky_post,
        )

        response = provider.create_message(
            model="deepseek-v4-pro",
            system="",
            messages=[],
            tools=[],
            max_tokens=128,
        )

        self.assertEqual(calls, [9, 9])
        self.assertEqual(response.content[0]["text"], "Recovered.")

    def test_does_not_retry_non_retryable_deepseek_errors(self):
        calls = 0

        def failing_post(url, headers, payload, timeout_seconds):
            nonlocal calls
            calls += 1
            raise DeepSeekAPIError(400, "bad request")

        provider = DeepSeekProvider(
            api_key="test-key",
            max_retries=3,
            retry_backoff_seconds=0,
            http_post=failing_post,
        )

        with self.assertRaises(DeepSeekAPIError):
            provider.create_message(
                model="deepseek-v4-pro",
                system="",
                messages=[],
                tools=[],
                max_tokens=128,
            )
        self.assertEqual(calls, 1)


class TestTrajectoryStore(unittest.TestCase):
    def test_saves_state_snapshot_and_events(self):
        with tempfile.TemporaryDirectory() as tempdir:
            store = TrajectoryStore(tempdir)
            state = AgentState(goal="inspect repo")
            state.start()

            store.record_state(state, "task_started", {"goal": state.goal})

            snapshot = store.load_state(state.task_id)
            events = store.read_events(state.task_id)

        self.assertEqual(snapshot["schema_version"], SCHEMA_VERSION)
        self.assertEqual(snapshot["state"]["goal"], "inspect repo")
        self.assertEqual(snapshot["state"]["status"], "running")
        self.assertEqual(events[0]["event_type"], "task_started")


class TestAgentLoopWithPersistentTrajectory(unittest.TestCase):
    def test_mock_loop_records_tool_call_and_persists_run(self):
        provider = MockProvider([
            ModelResponse.tool_use(
                tool_use_id="toolu_1",
                name="glob",
                tool_input={"pattern": "*.py", "directory": "tests"},
                text="I will inspect the tests.",
                model="mock-model",
            ),
            ModelResponse.text("Done.", model="mock-model"),
        ])

        with tempfile.TemporaryDirectory() as tempdir:
            config = Config(
                model_provider="mock",
                model="mock-model",
                max_turns=3,
                permission_mode=PermissionMode.AUTO,
                trajectory_dir=tempdir,
            )
            agent = AgentLoop(config=config, provider=provider)

            with redirect_stdout(StringIO()):
                final_text = agent.run("inspect tests")

            state = agent.last_state
            self.assertIsNotNone(state)
            assert state is not None

            snapshot = agent.trajectory_store.load_state(state.task_id)
            events = agent.trajectory_store.read_events(state.task_id)

        event_types = [event["event_type"] for event in events]
        self.assertEqual(final_text, "Done.")
        self.assertEqual(state.status.value, "succeeded")
        self.assertEqual(state.turn_index, 1)
        self.assertEqual(snapshot["state"]["trajectory"][0]["action"]["tool_name"], "glob")
        self.assertIn("task_started", event_types)
        self.assertIn("model_response", event_types)
        self.assertIn("tool_observation", event_types)
        self.assertIn("task_finished", event_types)
        self.assertEqual(provider.requests[1]["messages"][-1]["content"][0]["tool_use_id"], "toolu_1")

    def test_reusing_agent_isolates_conversation_context_per_run(self):
        provider = MockProvider([
            ModelResponse.text("First done.", model="mock-model"),
            ModelResponse.text("Second done.", model="mock-model"),
        ])
        agent = AgentLoop(
            config=Config(
                model_provider="mock",
                model="mock-model",
                permission_mode=PermissionMode.AUTO,
                trajectory_dir=None,
            ),
            provider=provider,
        )

        with redirect_stdout(StringIO()):
            first_text = agent.run("first task")
            first_task_id = agent.last_state.task_id
            second_text = agent.run("second task")
            second_task_id = agent.last_state.task_id

        first_request = provider.requests[0]["messages"]
        second_request = provider.requests[1]["messages"]

        self.assertEqual(first_text, "First done.")
        self.assertEqual(second_text, "Second done.")
        self.assertNotEqual(first_task_id, second_task_id)
        self.assertEqual(first_request[0]["content"], "first task")
        self.assertIn("Runtime execution plan:", str(first_request[1]["content"]))
        self.assertEqual(second_request[0]["content"], "second task")
        self.assertNotIn("first task", str(second_request))

    def test_deepseek_provider_completes_full_agent_tool_round_trip(self):
        responses = [
            {
                "model": "deepseek-v4-pro",
                "choices": [{
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": "I will inspect the workspace.",
                        "tool_calls": [{
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "glob",
                                "arguments": '{"pattern": "*.py"}',
                            },
                        }],
                    },
                }],
                "usage": {"prompt_tokens": 12, "completion_tokens": 5},
            },
            {
                "model": "deepseek-v4-pro",
                "choices": [{
                    "finish_reason": "stop",
                    "message": {"content": "Workspace inspected."},
                }],
                "usage": {"prompt_tokens": 24, "completion_tokens": 3},
            },
        ]
        requests: list[dict] = []

        def fake_post(url, headers, payload, timeout_seconds):
            requests.append({
                "url": url,
                "headers": headers,
                "payload": payload,
                "timeout_seconds": timeout_seconds,
            })
            return responses.pop(0)

        with tempfile.TemporaryDirectory() as tempdir:
            Path(tempdir, "sample.py").write_text("value = 1\n", encoding="utf-8")
            provider = DeepSeekProvider(
                api_key="test-key",
                base_url="https://example.test",
                http_post=fake_post,
            )
            agent = AgentLoop(
                config=Config(
                    model_provider="deepseek",
                    model="deepseek-v4-pro",
                    permission_mode=PermissionMode.AUTO,
                    workspace_root=tempdir,
                    trajectory_dir=None,
                ),
                provider=provider,
            )

            with redirect_stdout(StringIO()):
                final_text = agent.run("inspect Python files")

            state = agent.last_state

        self.assertEqual(final_text, "Workspace inspected.")
        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(state.status.value, "succeeded")
        self.assertEqual(state.run_budget_report["input_tokens"], 36)
        self.assertEqual(state.run_budget_report["output_tokens"], 8)
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0]["headers"]["Authorization"], "Bearer test-key")
        second_messages = requests[1]["payload"]["messages"]
        self.assertEqual(second_messages[-1]["role"], "tool")
        self.assertEqual(second_messages[-1]["tool_call_id"], "call_1")
        self.assertIn("sample.py", second_messages[-1]["content"])


if __name__ == "__main__":
    unittest.main()
