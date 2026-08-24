from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any


class PermissionMode(Enum):
    ASK = "ask"
    AUTO = "auto"
    PLAN = "plan"


@dataclass
class Config:
    model_provider: str = "anthropic"
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 8192
    api_timeout_seconds: float = 120.0
    api_max_retries: int = 0
    api_retry_backoff_seconds: float = 1.0
    max_turns: int = 30
    max_tool_calls: int | None = None
    max_run_seconds: float | None = None
    max_context_messages: int = 100
    max_output_chars: int = 50_000
    workspace_root: str = "."
    enforce_workspace_paths: bool = True
    enable_context_ranking: bool = True
    enable_runtime_planning: bool = True
    enable_long_term_memory: bool = False
    memory_store_path: str | None = ".codeagentx/memory/memories.jsonl"
    memory_retrieval_limit: int = 3
    memory_min_score: int = 0
    memory_prompt_max_chars: int = 2_500
    context_ranking_limit: int = 6
    context_ranking_max_files: int = 1_000
    context_ranking_max_terms: int = 16
    context_ranking_max_text_hits_per_term: int = 5
    patch_backup_dir: str = ".codeagentx/patch_backups"
    enable_patch_policy: bool = True
    patch_policy_forbidden_paths: list[str] = field(default_factory=lambda: [
        ".git/*",
        ".env",
        ".env.*",
        "*.pem",
        "*.key",
        "id_rsa",
        "id_ed25519",
        "secrets.*",
    ])
    patch_policy_max_changed_files: int = 20
    patch_policy_max_total_changed_lines: int = 1_200
    patch_policy_max_single_file_bytes_delta: int = 1_000_000
    patch_policy_fail_on_empty_patch: bool = True
    auto_rollback_on_verification_failure: bool = False
    trajectory_dir: str | None = ".codeagentx/trajectories"
    enable_task_constraints: bool = True
    task_success_criteria: list[str] = field(default_factory=list)
    task_required_changed_paths: list[str] = field(default_factory=list)
    task_forbidden_changed_paths: list[str] = field(default_factory=list)
    task_required_final_response_substrings: list[str] = field(default_factory=list)
    task_forbidden_final_response_substrings: list[str] = field(default_factory=list)
    verification_command: str | None = None
    verification_timeout_seconds: int = 120
    verification_sandbox: str = "local"
    enable_sandbox_artifacts: bool = True
    sandbox_artifact_dir: str | None = None
    sandbox_artifact_task_id: str | None = None
    sandbox_snapshot_max_files: int = 2_000
    sandbox_snapshot_max_recorded_files: int = 100
    docker_binary: str = "docker"
    docker_sandbox_image: str = "python:3.12-slim"
    docker_sandbox_network: str = "none"
    docker_sandbox_memory: str | None = None
    docker_sandbox_cpus: str | None = None
    docker_sandbox_user: str | None = None
    docker_sandbox_mount_mode: str = "rw"
    enable_failure_reflection: bool = True
    max_reflection_retries: int = 0
    reflection_retry_prompt_max_chars: int = 6_000
    enable_retry_strategy_matrix: bool = True
    enable_tool_planning_guidance: bool = True
    permission_mode: PermissionMode = PermissionMode.ASK
    allowed_commands: list[str] = field(default_factory=lambda: [
        "ls", "cat", "head", "tail", "wc", "find", "grep", "rg",
        "git status", "git diff", "git log", "git branch",
        "python", "python3", "pip", "npm", "node",
        "echo", "pwd", "which", "env", "date",
    ])
    denied_patterns: list[str] = field(default_factory=lambda: [
        "rm -rf /", "rm -rf ~", "sudo rm",
        "git push --force", "git reset --hard",
        "> /dev/sda", "mkfs", "dd if=",
        ":(){ :|:& };:",
    ])

    @classmethod
    def from_env(
        cls,
        *,
        env_path: str | Path | None = None,
        **overrides: Any,
    ) -> "Config":
        """Build runtime configuration from the local .env file and process env."""

        load_env_file(env_path)
        config = cls(
            model_provider=env_str("CODEAGENTX_PROVIDER", cls.model_provider),
            model=env_str("CODEAGENTX_MODEL", cls.model),
            max_tokens=env_int("CODEAGENTX_MAX_TOKENS", cls.max_tokens),
            api_timeout_seconds=env_float(
                "CODEAGENTX_API_TIMEOUT_SECONDS",
                cls.api_timeout_seconds,
            ),
            api_max_retries=env_int(
                "CODEAGENTX_API_MAX_RETRIES",
                cls.api_max_retries,
            ),
            api_retry_backoff_seconds=env_float(
                "CODEAGENTX_API_RETRY_BACKOFF_SECONDS",
                cls.api_retry_backoff_seconds,
            ),
            max_turns=env_int("CODEAGENTX_MAX_TURNS", cls.max_turns),
            max_tool_calls=env_optional_int("CODEAGENTX_MAX_TOOL_CALLS"),
            max_run_seconds=env_optional_float("CODEAGENTX_MAX_RUN_SECONDS"),
            max_context_messages=env_int(
                "CODEAGENTX_MAX_CONTEXT_MESSAGES",
                cls.max_context_messages,
            ),
            workspace_root=env_str(
                "CODEAGENTX_WORKSPACE_ROOT",
                cls.workspace_root,
            ),
            enforce_workspace_paths=env_bool(
                "CODEAGENTX_ENFORCE_WORKSPACE_PATHS",
                cls.enforce_workspace_paths,
            ),
            enable_long_term_memory=env_bool(
                "CODEAGENTX_ENABLE_LONG_TERM_MEMORY",
                cls.enable_long_term_memory,
            ),
            memory_store_path=env_optional_str(
                "CODEAGENTX_MEMORY_STORE_PATH",
                cls.memory_store_path,
            ),
            memory_retrieval_limit=env_int(
                "CODEAGENTX_MEMORY_RETRIEVAL_LIMIT",
                cls.memory_retrieval_limit,
            ),
            memory_min_score=env_int(
                "CODEAGENTX_MEMORY_MIN_SCORE",
                cls.memory_min_score,
            ),
            memory_prompt_max_chars=env_int(
                "CODEAGENTX_MEMORY_PROMPT_MAX_CHARS",
                cls.memory_prompt_max_chars,
            ),
            context_ranking_limit=env_int(
                "CODEAGENTX_CONTEXT_RANKING_LIMIT",
                cls.context_ranking_limit,
            ),
            trajectory_dir=env_optional_str(
                "CODEAGENTX_TRAJECTORY_DIR",
                cls.trajectory_dir,
            ),
            permission_mode=env_permission_mode(
                "CODEAGENTX_PERMISSION_MODE",
                cls.permission_mode,
            ),
        )
        return replace(config, **overrides) if overrides else config


def load_env_file(path: str | Path | None = None) -> None:
    """Load simple KEY=VALUE pairs from .env without overriding process env."""

    env_path = _resolve_env_path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = _strip_env_quotes(value.strip())


def env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value not in (None, "") else default


def env_optional_str(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return default if value in (None, "") else value


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    try:
        return int(value)
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    try:
        return float(value)
    except ValueError:
        return default


def env_optional_int(name: str, default: int | None = None) -> int | None:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    try:
        return int(value)
    except ValueError:
        return default


def env_optional_float(name: str, default: float | None = None) -> float | None:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    try:
        return float(value)
    except ValueError:
        return default


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    normalized = value.strip().lower()
    if normalized in ("1", "true", "yes", "y", "on"):
        return True
    if normalized in ("0", "false", "no", "n", "off"):
        return False
    return default


def env_permission_mode(name: str, default: PermissionMode) -> PermissionMode:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    try:
        return PermissionMode(value.strip().lower())
    except ValueError:
        return default


def _resolve_env_path(path: str | Path | None) -> Path:
    requested = Path(path or ".env").expanduser()
    if requested.is_absolute():
        return requested
    cwd_path = Path.cwd() / requested
    if cwd_path.exists():
        return cwd_path
    project_path = Path(__file__).resolve().parents[1] / requested
    if project_path.exists():
        return project_path
    return cwd_path


def _strip_env_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value
