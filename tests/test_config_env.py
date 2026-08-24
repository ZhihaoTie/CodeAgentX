import os
import tempfile
import unittest
from pathlib import Path

from codeagentx.config import Config, PermissionMode, env_float, env_int, env_str, load_env_file


class EnvConfigTests(unittest.TestCase):
    def test_load_env_file_reads_values_without_overriding_existing_env(self):
        with tempfile.TemporaryDirectory() as tempdir:
            env_path = Path(tempdir) / ".env"
            env_path.write_text(
                "\n".join([
                    "CODEAGENTX_PROVIDER=deepseek",
                    "CODEAGENTX_MODEL=\"deepseek-v4-pro\"",
                    "CODEAGENTX_MAX_TOKENS=4096",
                    "CODEAGENTX_API_RETRY_BACKOFF_SECONDS=0.25",
                ]),
                encoding="utf-8",
            )

            old_provider = os.environ.get("CODEAGENTX_PROVIDER")
            old_model = os.environ.get("CODEAGENTX_MODEL")
            old_tokens = os.environ.get("CODEAGENTX_MAX_TOKENS")
            old_backoff = os.environ.get("CODEAGENTX_API_RETRY_BACKOFF_SECONDS")
            try:
                os.environ["CODEAGENTX_PROVIDER"] = "mock"
                os.environ.pop("CODEAGENTX_MODEL", None)
                os.environ.pop("CODEAGENTX_MAX_TOKENS", None)
                os.environ.pop("CODEAGENTX_API_RETRY_BACKOFF_SECONDS", None)

                load_env_file(env_path)

                self.assertEqual(env_str("CODEAGENTX_PROVIDER", "anthropic"), "mock")
                self.assertEqual(env_str("CODEAGENTX_MODEL", ""), "deepseek-v4-pro")
                self.assertEqual(env_int("CODEAGENTX_MAX_TOKENS", 0), 4096)
                self.assertEqual(env_float("CODEAGENTX_API_RETRY_BACKOFF_SECONDS", 0), 0.25)
            finally:
                _restore_env("CODEAGENTX_PROVIDER", old_provider)
                _restore_env("CODEAGENTX_MODEL", old_model)
                _restore_env("CODEAGENTX_MAX_TOKENS", old_tokens)
                _restore_env("CODEAGENTX_API_RETRY_BACKOFF_SECONDS", old_backoff)

    def test_config_from_env_builds_runtime_config(self):
        with tempfile.TemporaryDirectory() as tempdir:
            env_path = Path(tempdir) / ".env"
            env_path.write_text(
                "\n".join([
                    "CODEAGENTX_PROVIDER=deepseek",
                    "CODEAGENTX_MODEL=deepseek-v4-pro",
                    "CODEAGENTX_MAX_TOKENS=4096",
                    "CODEAGENTX_API_TIMEOUT_SECONDS=45",
                    "CODEAGENTX_API_MAX_RETRIES=2",
                    "CODEAGENTX_API_RETRY_BACKOFF_SECONDS=0.5",
                    "CODEAGENTX_MAX_TURNS=8",
                    "CODEAGENTX_MAX_TOOL_CALLS=20",
                    "CODEAGENTX_MAX_RUN_SECONDS=90",
                    "CODEAGENTX_PERMISSION_MODE=auto",
                    "CODEAGENTX_WORKSPACE_ROOT=D:\\workspace",
                    "CODEAGENTX_ENABLE_LONG_TERM_MEMORY=true",
                    "CODEAGENTX_MEMORY_STORE_PATH=.codeagentx/memory/test.jsonl",
                    "CODEAGENTX_MEMORY_RETRIEVAL_LIMIT=4",
                    "CODEAGENTX_MEMORY_MIN_SCORE=42",
                    "CODEAGENTX_MEMORY_PROMPT_MAX_CHARS=1800",
                ]),
                encoding="utf-8",
            )

            names = [
                "CODEAGENTX_PROVIDER",
                "CODEAGENTX_MODEL",
                "CODEAGENTX_MAX_TOKENS",
                "CODEAGENTX_API_TIMEOUT_SECONDS",
                "CODEAGENTX_API_MAX_RETRIES",
                "CODEAGENTX_API_RETRY_BACKOFF_SECONDS",
                "CODEAGENTX_MAX_TURNS",
                "CODEAGENTX_MAX_TOOL_CALLS",
                "CODEAGENTX_MAX_RUN_SECONDS",
                "CODEAGENTX_PERMISSION_MODE",
                "CODEAGENTX_WORKSPACE_ROOT",
                "CODEAGENTX_ENABLE_LONG_TERM_MEMORY",
                "CODEAGENTX_MEMORY_STORE_PATH",
                "CODEAGENTX_MEMORY_RETRIEVAL_LIMIT",
                "CODEAGENTX_MEMORY_MIN_SCORE",
                "CODEAGENTX_MEMORY_PROMPT_MAX_CHARS",
            ]
            previous = {name: os.environ.get(name) for name in names}
            try:
                for name in names:
                    os.environ.pop(name, None)

                config = Config.from_env(env_path=env_path)
            finally:
                for name, value in previous.items():
                    _restore_env(name, value)

        self.assertEqual(config.model_provider, "deepseek")
        self.assertEqual(config.model, "deepseek-v4-pro")
        self.assertEqual(config.max_tokens, 4096)
        self.assertEqual(config.api_timeout_seconds, 45.0)
        self.assertEqual(config.api_max_retries, 2)
        self.assertEqual(config.api_retry_backoff_seconds, 0.5)
        self.assertEqual(config.max_turns, 8)
        self.assertEqual(config.max_tool_calls, 20)
        self.assertEqual(config.max_run_seconds, 90.0)
        self.assertEqual(config.permission_mode, PermissionMode.AUTO)
        self.assertEqual(config.workspace_root, "D:\\workspace")
        self.assertTrue(config.enable_long_term_memory)
        self.assertEqual(config.memory_store_path, ".codeagentx/memory/test.jsonl")
        self.assertEqual(config.memory_retrieval_limit, 4)
        self.assertEqual(config.memory_min_score, 42)
        self.assertEqual(config.memory_prompt_max_chars, 1800)


def _restore_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


if __name__ == "__main__":
    unittest.main()
