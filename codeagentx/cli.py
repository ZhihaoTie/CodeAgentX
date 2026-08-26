"""CLI entry point for CodeAgent-X."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from urllib import error, request

from .agent import AgentLoop
from .config import (
    Config,
    PermissionMode,
    env_float,
    env_bool,
    env_int,
    env_optional_float,
    env_optional_int,
    env_str,
    load_env_file,
)
from .sandbox import LocalSandboxRunner, SandboxSpec
from .tools.base import ToolRegistry
from .terminal import write_text


BANNER = """
CodeAgent-X v0.18.0
Autonomous Software Engineering Agent Runtime

Type your message to start. Commands:
  /tools   -- list available tools
  /mode    -- show/change permission mode
  /help    -- show help
  /quit    -- exit
""".strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="CodeAgent-X -- an autonomous software engineering agent runtime",
    )
    parser.add_argument(
        "--provider",
        choices=["anthropic", "deepseek", "mock"],
        default=env_str("CODEAGENTX_PROVIDER", "anthropic"),
        help="Model provider to use (default: CODEAGENTX_PROVIDER or anthropic)",
    )
    parser.add_argument(
        "--model",
        default=env_str("CODEAGENTX_MODEL", "claude-sonnet-4-20250514"),
        help="Model name passed to the selected provider (default: CODEAGENTX_MODEL or Claude Sonnet 4)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=env_int("CODEAGENTX_MAX_TOKENS", 8192),
        help="Max tokens per model response (default: CODEAGENTX_MAX_TOKENS or 8192)",
    )
    parser.add_argument(
        "--api-timeout",
        type=float,
        default=env_float("CODEAGENTX_API_TIMEOUT_SECONDS", 120.0),
        help="Model API timeout in seconds (default: CODEAGENTX_API_TIMEOUT_SECONDS or 120)",
    )
    parser.add_argument(
        "--api-max-retries",
        type=int,
        default=env_int("CODEAGENTX_API_MAX_RETRIES", 0),
        help="Model API retry attempts after the first request (default: CODEAGENTX_API_MAX_RETRIES or 0)",
    )
    parser.add_argument(
        "--api-retry-backoff",
        type=float,
        default=env_float("CODEAGENTX_API_RETRY_BACKOFF_SECONDS", 1.0),
        help="Base delay between model API retries in seconds (default: CODEAGENTX_API_RETRY_BACKOFF_SECONDS or 1.0)",
    )
    parser.add_argument(
        "--mode",
        choices=["ask", "auto", "plan"],
        default=env_str("CODEAGENTX_PERMISSION_MODE", "ask"),
        help="Permission mode (default: CODEAGENTX_PERMISSION_MODE or ask)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Shortcut for --mode auto in one-shot runs",
    )
    parser.add_argument(
        "--branch",
        nargs="?",
        const="",
        default=None,
        help=(
            "Create and switch to a git branch before running. "
            "Pass a name or omit the value for an auto-generated branch."
        ),
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Commit local changes after a successful run/verification",
    )
    parser.add_argument(
        "--commit-message",
        default=None,
        help="Commit message used with --commit",
    )
    parser.add_argument(
        "--pr",
        action="store_true",
        help="Push the committed branch and create a GitHub pull request",
    )
    parser.add_argument(
        "--pr-title",
        default=None,
        help="Pull request title used with --pr",
    )
    parser.add_argument(
        "--pr-body",
        default=None,
        help="Pull request body used with --pr",
    )
    parser.add_argument(
        "--base",
        default=env_str("CODEAGENTX_GITHUB_BASE_BRANCH", "main"),
        help="Base branch for --pr (default: CODEAGENTX_GITHUB_BASE_BRANCH or main)",
    )
    parser.add_argument(
        "--remote",
        default=env_str("CODEAGENTX_GITHUB_REMOTE_NAME", "origin"),
        help="Git remote used by --pr (default: CODEAGENTX_GITHUB_REMOTE_NAME or origin)",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=env_int("CODEAGENTX_MAX_TURNS", 30),
        help="Max agent loop turns per message (default: CODEAGENTX_MAX_TURNS or 30)",
    )
    parser.add_argument(
        "--max-tool-calls",
        type=int,
        default=env_optional_int("CODEAGENTX_MAX_TOOL_CALLS"),
        help="Optional hard limit for tool calls in one task run",
    )
    parser.add_argument(
        "--max-run-seconds",
        type=float,
        default=env_optional_float("CODEAGENTX_MAX_RUN_SECONDS"),
        help="Optional hard wall-clock limit for one task run",
    )
    parser.add_argument(
        "--workspace-root",
        default=env_str("CODEAGENTX_WORKSPACE_ROOT", "."),
        help="Workspace root that tools are allowed to access (default: CODEAGENTX_WORKSPACE_ROOT or current directory)",
    )
    parser.add_argument(
        "--allow-outside-workspace",
        action="store_true",
        help="Disable workspace path restrictions for this run",
    )
    parser.add_argument(
        "--no-context-ranking",
        action="store_true",
        help="Disable ranked context generation before reflection retry",
    )
    parser.add_argument(
        "--no-runtime-planning",
        action="store_true",
        help="Disable runtime task plan lifecycle tracking",
    )
    parser.add_argument(
        "--context-ranking-limit",
        type=int,
        default=6,
        help="Max ranked context candidates injected into retry prompts (default: 6)",
    )
    parser.add_argument(
        "--enable-memory",
        action="store_true",
        default=env_bool("CODEAGENTX_ENABLE_LONG_TERM_MEMORY", False),
        help="Enable verified long-term memory retrieval and extraction",
    )
    parser.add_argument(
        "--memory-store-path",
        default=env_str("CODEAGENTX_MEMORY_STORE_PATH", ".codeagentx/memory/memories.jsonl"),
        help="JSONL store for verified long-term memory records",
    )
    parser.add_argument(
        "--memory-retrieval-limit",
        type=int,
        default=env_int("CODEAGENTX_MEMORY_RETRIEVAL_LIMIT", 3),
        help="Max long-term memory records injected into prompts (default: 3)",
    )
    parser.add_argument(
        "--memory-min-score",
        type=int,
        default=env_int("CODEAGENTX_MEMORY_MIN_SCORE", 0),
        help="Minimum retrieval score required before a memory is injected (default: 0)",
    )
    parser.add_argument(
        "--memory-prompt-max-chars",
        type=int,
        default=env_int("CODEAGENTX_MEMORY_PROMPT_MAX_CHARS", 2500),
        help="Max characters for rendered long-term memory prompt context",
    )
    parser.add_argument(
        "--trajectory-dir",
        default=".codeagentx/trajectories",
        help="Directory for trajectory JSON/JSONL artifacts",
    )
    parser.add_argument(
        "--no-trajectory",
        action="store_true",
        help="Disable trajectory persistence for this run",
    )
    parser.add_argument(
        "--auto-rollback-on-failure",
        action="store_true",
        help="Rollback write/edit patches when explicit verification fails",
    )
    parser.add_argument(
        "--no-patch-policy",
        action="store_true",
        help="Disable patch policy checks at verification time",
    )
    parser.add_argument(
        "--patch-policy-max-files",
        type=int,
        default=20,
        help="Max changed files allowed by patch policy (default: 20)",
    )
    parser.add_argument(
        "--patch-policy-max-lines",
        type=int,
        default=1200,
        help="Max added+deleted diff lines allowed by patch policy (default: 1200)",
    )
    parser.add_argument(
        "--benchmark",
        default=None,
        help="Run a benchmark task spec JSON instead of interactive mode",
    )
    parser.add_argument(
        "--swebench",
        default=None,
        help="Run SWE-bench style JSON/JSONL tasks by provisioning git workspaces first",
    )
    parser.add_argument(
        "--swebench-dry-run",
        action="store_true",
        help="Load/filter SWE-bench tasks and write a manifest without provisioning or running the agent",
    )
    parser.add_argument(
        "--swebench-preflight",
        action="store_true",
        help="Run SWE-bench task and environment checks without provisioning or running the agent",
    )
    parser.add_argument(
        "--swebench-no-auto-preflight",
        action="store_true",
        help=(
            "Skip the automatic SWE-bench preflight gate before official "
            "evaluation or Docker sandbox runs"
        ),
    )
    parser.add_argument(
        "--swebench-report",
        default=None,
        help="Generate/evaluate SWE-bench predictions from an existing CodeAgent-X benchmark report",
    )
    parser.add_argument(
        "--swebench-repair-output",
        default=None,
        help=(
            "With --swebench-report, write a diagnostic repair benchmark spec "
            "from official SWE-bench failure evidence and exit"
        ),
    )
    parser.add_argument(
        "--swebench-repair-include-resolved",
        action="store_true",
        help="Include already official-resolved tasks in --swebench-repair-output",
    )
    parser.add_argument(
        "--swebench-repair-max-excerpt-chars",
        type=int,
        default=2500,
        help="Max official failure excerpt characters injected into each repair task",
    )
    parser.add_argument(
        "--swebench-repair-max-patch-chars",
        type=int,
        default=4000,
        help="Max previous patch characters injected into each repair task",
    )
    parser.add_argument(
        "--swebench-summary",
        nargs="+",
        default=None,
        help="Aggregate annotated SWE-bench benchmark report JSON files and exit",
    )
    parser.add_argument(
        "--swebench-summary-output",
        default=None,
        help="Output path for --swebench-summary JSON (default: .codeagentx/swebench/swebench_experiment_summary.json)",
    )
    parser.add_argument(
        "--swebench-summary-markdown-output",
        default=None,
        help="Output path for --swebench-summary Markdown (default: JSON output path with .md)",
    )
    parser.add_argument(
        "--benchmark-ablation",
        action="store_true",
        help="Run configured benchmark ablation variants and write an ablation report",
    )
    parser.add_argument(
        "--benchmark-output-dir",
        default=".codeagentx/benchmarks",
        help="Directory for benchmark report artifacts",
    )
    parser.add_argument(
        "--benchmark-task-id",
        action="append",
        default=[],
        help="Run only the benchmark task with this id; repeat to select multiple tasks",
    )
    parser.add_argument(
        "--benchmark-limit",
        type=int,
        default=None,
        help="Run only the first N benchmark tasks after filtering",
    )
    parser.add_argument(
        "--benchmark-variant",
        action="append",
        default=[],
        help="Run only the ablation variant with this name; repeat to select multiple variants",
    )
    parser.add_argument(
        "--benchmark-memory-policy",
        choices=["shared", "isolated", "disabled"],
        default=env_str("CODEAGENTX_BENCHMARK_MEMORY_POLICY", "shared"),
        help=(
            "Benchmark memory fairness policy: shared permits cross-task memory, "
            "isolated resets memory per task, disabled turns long-term memory off"
        ),
    )
    parser.add_argument(
        "--benchmark-report",
        default=None,
        help="Render an existing benchmark report JSON to Markdown and exit",
    )
    parser.add_argument(
        "--benchmark-report-output",
        default=None,
        help="Output path for --benchmark-report Markdown (default: same path with .md)",
    )
    parser.add_argument(
        "--swebench-workspaces-root",
        default=".codeagentx/swebench/workspaces",
        help="Directory for provisioned SWE-bench task workspaces",
    )
    parser.add_argument(
        "--swebench-repo-cache-root",
        default=".codeagentx/swebench/repos",
        help="Directory for SWE-bench bare mirror repository cache",
    )
    parser.add_argument(
        "--swebench-no-repo-cache",
        action="store_true",
        help="Clone SWE-bench repositories directly without using a local mirror cache",
    )
    parser.add_argument(
        "--swebench-repo-url-template",
        default="https://github.com/{repo}.git",
        help="Template used to resolve SWE-bench owner/repo values into clone URLs",
    )
    parser.add_argument(
        "--swebench-refresh-cache",
        action="store_true",
        help="Refresh an existing SWE-bench repository cache before provisioning",
    )
    parser.add_argument(
        "--swebench-no-overwrite",
        action="store_true",
        help="Fail if a SWE-bench task workspace already exists instead of recreating it",
    )
    parser.add_argument(
        "--swebench-update-submodules",
        action="store_true",
        help="Run git submodule update --init --recursive after checkout",
    )
    parser.add_argument(
        "--swebench-git-timeout",
        type=int,
        default=300,
        help="Timeout in seconds for each SWE-bench git command",
    )
    parser.add_argument(
        "--swebench-setup-command",
        default=None,
        help="Setup command attached to every provisioned SWE-bench benchmark task",
    )
    parser.add_argument(
        "--swebench-predictions-output",
        default=None,
        help="Output path for generated SWE-bench predictions JSONL",
    )
    parser.add_argument(
        "--swebench-manifest-output",
        default=None,
        help="Output path for --swebench-dry-run task manifest",
    )
    parser.add_argument(
        "--swebench-preflight-output",
        default=None,
        help="Output path for --swebench-preflight JSON report",
    )
    parser.add_argument(
        "--swebench-model-name",
        default=None,
        help="model_name_or_path value written to SWE-bench predictions",
    )
    parser.add_argument(
        "--swebench-skip-empty-patches",
        action="store_true",
        help="Exclude SWE-bench tasks without a generated patch from predictions",
    )
    parser.add_argument(
        "--swebench-evaluate",
        action="store_true",
        help="Run the official SWE-bench evaluator after generating predictions",
    )
    parser.add_argument(
        "--swebench-eval-dataset",
        default="SWE-bench/SWE-bench_Lite",
        help="Dataset name passed to the SWE-bench evaluator",
    )
    parser.add_argument(
        "--swebench-eval-split",
        default="test",
        help="Dataset split passed to the SWE-bench evaluator",
    )
    parser.add_argument(
        "--swebench-eval-run-id",
        default=None,
        help="Run id passed to the SWE-bench evaluator (default: benchmark run id)",
    )
    parser.add_argument(
        "--swebench-eval-max-workers",
        type=int,
        default=4,
        help="Max worker count passed to the SWE-bench evaluator",
    )
    parser.add_argument(
        "--swebench-eval-timeout",
        type=int,
        default=1800,
        help="Per-instance timeout passed to the SWE-bench evaluator",
    )
    parser.add_argument(
        "--swebench-eval-process-timeout",
        type=int,
        default=None,
        help="Optional wall-clock timeout for the evaluator subprocess",
    )
    parser.add_argument(
        "--swebench-eval-python-executable",
        default=None,
        help="Python executable used for the official SWE-bench evaluator (default: current Python)",
    )
    parser.add_argument(
        "--swebench-eval-command-prefix",
        default=None,
        help=(
            "Optional command prefix prepended before evaluator Python, for example "
            "'docker run --rm -v D:/CodeAgent-X:/workspace -w /workspace image'"
        ),
    )
    parser.add_argument(
        "--swebench-eval-cache-level",
        choices=["none", "base", "env", "instance"],
        default="env",
        help="Cache level passed to the SWE-bench evaluator",
    )
    parser.add_argument(
        "--swebench-eval-clean",
        action="store_true",
        help="Ask the SWE-bench evaluator to clean generated images/containers",
    )
    parser.add_argument(
        "--swebench-eval-namespace",
        default="swebench",
        help="Docker namespace passed to the SWE-bench evaluator",
    )
    parser.add_argument(
        "--swebench-eval-no-namespace",
        action="store_true",
        help="Do not pass a Docker namespace to the SWE-bench evaluator",
    )
    parser.add_argument(
        "--swebench-eval-report-dir",
        default=None,
        help="Report directory passed to the SWE-bench evaluator",
    )
    parser.add_argument(
        "--swebench-eval-results-path",
        default=None,
        help="Official SWE-bench results JSON/JSONL path used to annotate the benchmark report",
    )
    parser.add_argument(
        "--swebench-eval-artifact-output",
        default=None,
        help="Output path for raw SWE-bench evaluator command result JSON",
    )
    parser.add_argument(
        "--swebench-docker-lifecycle-image",
        default="python:3.12-slim",
        help=(
            "Probe image used by --swebench-preflight to verify Docker can "
            "create and remove containers (default: python:3.12-slim)"
        ),
    )
    parser.add_argument(
        "--swebench-annotated-report-output",
        default=None,
        help="Output path for a benchmark report annotated with official SWE-bench results",
    )
    parser.add_argument(
        "--verify-command",
        default=None,
        help="Command to run after the model stops using tools",
    )
    parser.add_argument(
        "--verify",
        dest="verify_command",
        help="Alias for --verify-command, for example: --verify \"pytest -q\"",
    )
    parser.add_argument(
        "--no-task-constraints",
        action="store_true",
        help="Disable deterministic task constraint verification",
    )
    parser.add_argument(
        "--success-criterion",
        action="append",
        default=[],
        help="Record a task success criterion for verification audit metadata",
    )
    parser.add_argument(
        "--require-changed-path",
        action="append",
        default=[],
        help="Require at least one modified file matching this glob pattern",
    )
    parser.add_argument(
        "--forbid-changed-path",
        action="append",
        default=[],
        help="Fail verification if a modified file matches this glob pattern",
    )
    parser.add_argument(
        "--require-final-text",
        action="append",
        default=[],
        help="Require the final response to contain this substring",
    )
    parser.add_argument(
        "--forbid-final-text",
        action="append",
        default=[],
        help="Fail verification if the final response contains this substring",
    )
    parser.add_argument(
        "--task-success-criterion",
        dest="success_criterion",
        action="append",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--verify-timeout",
        type=int,
        default=120,
        help="Verification command timeout in seconds (default: 120)",
    )
    parser.add_argument(
        "--verification-sandbox",
        choices=["local", "docker"],
        default="local",
        help="Sandbox backend for verification commands (default: local)",
    )
    parser.add_argument(
        "--no-sandbox-artifacts",
        action="store_true",
        help="Disable sandbox stdout/stderr/result artifacts",
    )
    parser.add_argument(
        "--sandbox-artifact-dir",
        default=None,
        help="Directory for sandbox command artifacts",
    )
    parser.add_argument(
        "--sandbox-snapshot-max-files",
        type=int,
        default=2000,
        help="Max workspace files fingerprinted per sandbox artifact (default: 2000)",
    )
    parser.add_argument(
        "--sandbox-snapshot-max-recorded-files",
        type=int,
        default=100,
        help="Max file hashes listed in each workspace snapshot (default: 100)",
    )
    parser.add_argument(
        "--docker-image",
        default="python:3.12-slim",
        help="Docker image used when --verification-sandbox docker is selected",
    )
    parser.add_argument(
        "--docker-network",
        default="none",
        help="Docker network mode for sandboxed commands (default: none)",
    )
    parser.add_argument(
        "--docker-memory",
        default=None,
        help="Docker memory limit, for example 1g or 512m",
    )
    parser.add_argument(
        "--docker-cpus",
        default=None,
        help="Docker CPU limit, for example 1.0 or 2",
    )
    parser.add_argument(
        "--no-failure-reflection",
        action="store_true",
        help="Disable deterministic failure reflection reports",
    )
    parser.add_argument(
        "--max-reflection-retries",
        type=int,
        default=0,
        help="Max automatic retries after retryable failure reflection (default: 0)",
    )
    parser.add_argument(
        "--no-retry-strategy-matrix",
        action="store_true",
        help="Disable strategy matrix guidance inside reflection retry prompts",
    )
    parser.add_argument(
        "--no-tool-planning-guidance",
        action="store_true",
        help="Disable runtime tool planning guidance derived from retry strategies",
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        default=None,
        help="Optional one-shot prompt (non-interactive mode)",
    )
    return parser


def run_interactive(agent: AgentLoop) -> None:
    """Interactive REPL loop."""
    print(BANNER)

    while True:
        try:
            user_input = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            cmd = user_input.lower().split()[0]
            if cmd in ("/quit", "/exit", "/q"):
                print("Goodbye!")
                break
            if cmd == "/tools":
                print("\nAvailable tools:")
                for tool in agent.registry.all_tools():
                    print(f"  - {tool.name}: {tool.description}")
                continue
            if cmd == "/mode":
                parts = user_input.split()
                if len(parts) > 1 and parts[1] in ("ask", "auto", "plan"):
                    agent.config.permission_mode = PermissionMode(parts[1])
                    print(f"Mode changed to: {parts[1]}")
                else:
                    print(f"Current mode: {agent.config.permission_mode.value}")
                    print("Usage: /mode [ask|auto|plan]")
                continue
            if cmd == "/help":
                print(BANNER)
                continue

            print(f"Unknown command: {cmd}. Type /help for help.")
            continue

        print()
        try:
            agent.run(user_input)
        except KeyboardInterrupt:
            print("\n(interrupted)")
        except Exception as exc:
            print(f"\nError: {exc}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    _configure_console()
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    one_shot_run = False
    interactive_chat = False
    fix_from_verifier = False
    if raw_argv and raw_argv[0] == "run":
        one_shot_run = True
        raw_argv = raw_argv[1:]
    elif raw_argv and raw_argv[0] == "fix":
        one_shot_run = True
        fix_from_verifier = True
        raw_argv = raw_argv[1:]
    elif raw_argv and raw_argv[0] == "chat":
        interactive_chat = True
        raw_argv = raw_argv[1:]

    parser = build_parser()
    if one_shot_run:
        args, extra_prompt_parts = parser.parse_known_args(raw_argv)
        if extra_prompt_parts:
            if args.prompt:
                args.prompt = " ".join([args.prompt, *extra_prompt_parts])
            else:
                parser.error(f"unrecognized arguments: {' '.join(extra_prompt_parts)}")
    else:
        args = parser.parse_args(raw_argv)
    if args.yes:
        args.mode = "auto"
    if one_shot_run and not fix_from_verifier and not args.prompt:
        parser.error('the "run" command requires a prompt, for example: codeagentx run "fix the failing tests"')
    if args.commit_message and not args.commit:
        parser.error("--commit-message requires --commit")
    if args.pr and not args.commit:
        parser.error("--pr requires --commit")
    if fix_from_verifier and not args.verify_command:
        parser.error('the "fix" command requires --verify, for example: codeagentx fix --verify "pytest -q"')
    if interactive_chat and args.prompt:
        parser.error('the "chat" command does not accept a prompt; use "run" for one-shot tasks')
    if one_shot_run and "--workspace-root" not in raw_argv:
        args.workspace_root = "."

    config = Config(
        model_provider=args.provider,
        model=args.model,
        max_tokens=args.max_tokens,
        api_timeout_seconds=args.api_timeout,
        api_max_retries=args.api_max_retries,
        api_retry_backoff_seconds=args.api_retry_backoff,
        permission_mode=PermissionMode(args.mode),
        max_turns=args.max_turns,
        max_tool_calls=args.max_tool_calls,
        max_run_seconds=args.max_run_seconds,
        workspace_root=args.workspace_root,
        enforce_workspace_paths=not args.allow_outside_workspace,
        enable_runtime_planning=not args.no_runtime_planning,
        enable_context_ranking=not args.no_context_ranking,
        context_ranking_limit=args.context_ranking_limit,
        enable_long_term_memory=args.enable_memory,
        memory_store_path=args.memory_store_path,
        memory_retrieval_limit=args.memory_retrieval_limit,
        memory_min_score=args.memory_min_score,
        memory_prompt_max_chars=args.memory_prompt_max_chars,
        enable_patch_policy=not args.no_patch_policy,
        patch_policy_max_changed_files=args.patch_policy_max_files,
        patch_policy_max_total_changed_lines=args.patch_policy_max_lines,
        auto_rollback_on_verification_failure=args.auto_rollback_on_failure,
        trajectory_dir=None if args.no_trajectory else args.trajectory_dir,
        enable_task_constraints=not args.no_task_constraints,
        task_success_criteria=args.success_criterion,
        task_required_changed_paths=args.require_changed_path,
        task_forbidden_changed_paths=args.forbid_changed_path,
        task_required_final_response_substrings=args.require_final_text,
        task_forbidden_final_response_substrings=args.forbid_final_text,
        verification_command=args.verify_command,
        verification_timeout_seconds=args.verify_timeout,
        verification_sandbox=args.verification_sandbox,
        enable_sandbox_artifacts=not args.no_sandbox_artifacts,
        sandbox_artifact_dir=args.sandbox_artifact_dir,
        sandbox_snapshot_max_files=args.sandbox_snapshot_max_files,
        sandbox_snapshot_max_recorded_files=args.sandbox_snapshot_max_recorded_files,
        docker_sandbox_image=args.docker_image,
        docker_sandbox_network=args.docker_network,
        docker_sandbox_memory=args.docker_memory,
        docker_sandbox_cpus=args.docker_cpus,
        enable_failure_reflection=not args.no_failure_reflection,
        max_reflection_retries=args.max_reflection_retries,
        enable_retry_strategy_matrix=not args.no_retry_strategy_matrix,
        enable_tool_planning_guidance=not args.no_tool_planning_guidance,
    )
    registry = ToolRegistry.default()
    benchmark_final_config_overrides = _benchmark_final_config_overrides(args)

    if args.benchmark and args.swebench:
        print("Benchmark error: use either --benchmark or --swebench, not both", file=sys.stderr)
        return 1
    if args.swebench_dry_run and not args.swebench:
        print("SWE-bench dry-run error: --swebench-dry-run requires --swebench", file=sys.stderr)
        return 1
    if args.swebench_preflight and not args.swebench:
        print("SWE-bench preflight error: --swebench-preflight requires --swebench", file=sys.stderr)
        return 1
    if args.swebench_report and (args.benchmark or args.swebench):
        print(
            "Benchmark error: use only one of --benchmark, --swebench, or --swebench-report",
            file=sys.stderr,
        )
        return 1
    if args.swebench_repair_output and not args.swebench_report:
        print(
            "SWE-bench repair error: --swebench-repair-output requires --swebench-report",
            file=sys.stderr,
        )
        return 1
    if args.swebench_summary and (
        args.benchmark
        or args.swebench
        or args.swebench_report
        or args.benchmark_report
        or args.benchmark_ablation
    ):
        print(
            "Benchmark error: use --swebench-summary without other benchmark/report modes",
            file=sys.stderr,
        )
        return 1
    if (args.swebench or args.swebench_report) and args.benchmark_ablation:
        print(
            "Benchmark error: --benchmark-ablation is not supported with --swebench or --swebench-report",
            file=sys.stderr,
        )
        return 1

    if args.benchmark_report:
        from .evaluation import save_benchmark_report_markdown

        try:
            output_path = save_benchmark_report_markdown(
                args.benchmark_report,
                args.benchmark_report_output,
            )
        except Exception as exc:
            print(f"Benchmark report error: {exc}", file=sys.stderr)
            return 1
        print(f"Markdown report: {output_path}")
        return 0

    if args.swebench_summary:
        from .evaluation import write_swebench_experiment_summary

        try:
            output_path = Path(
                args.swebench_summary_output
                or ".codeagentx/swebench/swebench_experiment_summary.json"
            )
            markdown_output_path = Path(
                args.swebench_summary_markdown_output
                or output_path.with_suffix(".md")
            )
            artifact = write_swebench_experiment_summary(
                args.swebench_summary,
                output_path,
                markdown_output_path=markdown_output_path,
            )
        except Exception as exc:
            print(f"SWE-bench summary error: {exc}", file=sys.stderr)
            return 1
        summary = artifact["summary"]
        evaluated_tasks = summary.get("evaluated_tasks", 0)
        resolved_tasks = summary.get("official_resolved_tasks", 0)
        evaluated_rate = summary.get("evaluated_official_resolved_rate")
        rate_text = (
            f"{evaluated_rate:.1%}"
            if isinstance(evaluated_rate, (int, float))
            else "n/a"
        )
        print(f"SWE-bench summary: {summary.get('task_count', 0)} task(s)")
        print(f"Official resolved: {resolved_tasks}/{evaluated_tasks} ({rate_text})")
        print(f"Summary: {artifact['summary_path']}")
        if artifact.get("markdown_path") is not None:
            print(f"Markdown: {artifact['markdown_path']}")
        return 0

    if args.benchmark:
        from .evaluation import (
            BenchmarkAblationRunner,
            BenchmarkRunner,
            load_benchmark_ablation_spec,
            load_benchmark_spec,
        )

        try:
            if args.benchmark_ablation:
                tasks, variants = load_benchmark_ablation_spec(args.benchmark)
                tasks = _filter_benchmark_tasks(
                    tasks,
                    task_ids=args.benchmark_task_id,
                    limit=args.benchmark_limit,
                )
                variants = _filter_benchmark_variants(
                    variants,
                    variant_names=args.benchmark_variant,
                )
                ablation_report = BenchmarkAblationRunner(
                    base_config=config,
                    registry=registry,
                    output_dir=args.benchmark_output_dir,
                    final_config_overrides=benchmark_final_config_overrides,
                    memory_policy=args.benchmark_memory_policy,
                ).run(tasks, variants=variants)
            else:
                tasks = load_benchmark_spec(args.benchmark)
                tasks = _filter_benchmark_tasks(
                    tasks,
                    task_ids=args.benchmark_task_id,
                    limit=args.benchmark_limit,
                )
                report = BenchmarkRunner(
                    base_config=config,
                    registry=registry,
                    output_dir=args.benchmark_output_dir,
                    final_config_overrides=benchmark_final_config_overrides,
                    memory_policy=args.benchmark_memory_policy,
                ).run(tasks)
        except Exception as exc:
            print(f"Benchmark error: {exc}", file=sys.stderr)
            return 1

        if args.benchmark_ablation:
            print(f"Benchmark ablation run: {ablation_report.run_id}")
            print(
                "Variants: "
                f"{len(ablation_report.variant_results)}; "
                f"task runs: {ablation_report.total_task_runs}"
            )
            print(f"Report: {ablation_report.report_path}")
            return 0

        print(f"Benchmark run: {report.run_id}")
        print(
            "Resolved: "
            f"{report.resolved_tasks}/{report.total_tasks} "
            f"({report.resolved_rate:.1%})"
        )
        print(f"Report: {report.report_path}")
        return 0 if report.failed_tasks == 0 else 1

    if args.swebench_report:
        try:
            report = _load_swebench_report_reference(args.swebench_report)
            if args.swebench_repair_output:
                repair_artifact = _write_swebench_repair_benchmark_for_report(
                    report,
                    args,
                )
                print(f"SWE-bench source report: {report.report_path}")
                print(f"Repair benchmark spec: {repair_artifact.output_path}")
                print(f"Repair tasks: {repair_artifact.repair_task_count}")
                print(
                    "Fairness: diagnostic-only; do not report as a fair "
                    "public SWE-bench score"
                )
                return 0
            preflight = _run_swebench_report_auto_preflight_if_needed(report, args)
            if preflight is not None:
                print(
                    "SWE-bench report auto preflight: "
                    f"{'passed' if preflight.passed else 'failed'}"
                )
                print(
                    "Checks: "
                    f"{len(preflight.checks)}; "
                    f"failures: {preflight.failure_count}; "
                    f"warnings: {preflight.warning_count}"
                )
                print(f"Preflight report: {preflight.report_path}")
                if not preflight.passed:
                    print(
                        "SWE-bench report error: automatic preflight failed; fix "
                        "the reported environment/configuration issue or pass "
                        "--swebench-no-auto-preflight to bypass.",
                        file=sys.stderr,
                    )
                    return 1
            predictions = _write_swebench_predictions_for_report(report, args)
            evaluation_result = (
                _run_swebench_official_evaluator(report, predictions, args)
                if args.swebench_evaluate
                else None
            )
            evaluation_artifact_path = (
                _write_swebench_evaluation_result_artifact(report, evaluation_result, args)
                if evaluation_result is not None
                else None
            )
            annotated_report_path = (
                _annotate_swebench_report_if_available(report, evaluation_result, args)
                if evaluation_result is not None or args.swebench_eval_results_path
                else None
            )
        except Exception as exc:
            print(f"SWE-bench report error: {exc}", file=sys.stderr)
            return 1

        print(f"SWE-bench source report: {report.report_path}")
        print(f"Predictions: {predictions.predictions_path}")
        if evaluation_result is not None:
            print(f"Evaluator exit: {evaluation_result.exit_code}")
            print(f"Evaluator results: {evaluation_result.results_path}")
        if evaluation_artifact_path is not None:
            print(f"Evaluator artifact: {evaluation_artifact_path}")
        if annotated_report_path is not None:
            print(f"Annotated report: {annotated_report_path}")
        if evaluation_result is not None and not evaluation_result.passed:
            return 1
        return 0

    if args.swebench:
        if args.swebench_preflight:
            try:
                tasks = _load_swebench_manifest_tasks(args)
                preflight = _write_swebench_preflight_for_tasks(tasks, args)
            except Exception as exc:
                print(f"SWE-bench preflight error: {exc}", file=sys.stderr)
                return 1

            print(f"SWE-bench preflight: {'passed' if preflight.passed else 'failed'}")
            print(
                "Checks: "
                f"{len(preflight.checks)}; "
                f"failures: {preflight.failure_count}; "
                f"warnings: {preflight.warning_count}"
            )
            print(f"Report: {preflight.report_path}")
            return 0 if preflight.passed else 1

        if args.swebench_dry_run:
            try:
                tasks = _load_swebench_manifest_tasks(args)
                manifest = _write_swebench_manifest_for_tasks(tasks, args)
            except Exception as exc:
                print(f"SWE-bench dry-run error: {exc}", file=sys.stderr)
                return 1

            print(f"SWE-bench dry run: {manifest.task_count} task(s)")
            print(f"Repositories: {len(manifest.repositories)}")
            print(f"Prompt leakage tasks: {manifest.prompt_leakage_count}")
            print(f"Manifest: {manifest.manifest_path}")
            return 0

        from .evaluation import BenchmarkRunner

        try:
            preflight = _run_swebench_auto_preflight_if_needed(args)
            if preflight is not None:
                print(
                    "SWE-bench auto preflight: "
                    f"{'passed' if preflight.passed else 'failed'}"
                )
                print(
                    "Checks: "
                    f"{len(preflight.checks)}; "
                    f"failures: {preflight.failure_count}; "
                    f"warnings: {preflight.warning_count}"
                )
                print(f"Preflight report: {preflight.report_path}")
                if not preflight.passed:
                    print(
                        "SWE-bench error: automatic preflight failed; fix the "
                        "reported environment/configuration issue or pass "
                        "--swebench-no-auto-preflight to bypass.",
                        file=sys.stderr,
                    )
                    return 1
            tasks = _load_swebench_benchmark_tasks(args)
            report = BenchmarkRunner(
                base_config=config,
                registry=registry,
                output_dir=args.benchmark_output_dir,
                final_config_overrides=benchmark_final_config_overrides,
                memory_policy=args.benchmark_memory_policy,
            ).run(tasks)
            predictions = _write_swebench_predictions_for_report(report, args)
            evaluation_result = (
                _run_swebench_official_evaluator(report, predictions, args)
                if args.swebench_evaluate
                else None
            )
            evaluation_artifact_path = (
                _write_swebench_evaluation_result_artifact(report, evaluation_result, args)
                if evaluation_result is not None
                else None
            )
            annotated_report_path = (
                _annotate_swebench_report_if_available(report, evaluation_result, args)
                if evaluation_result is not None or args.swebench_eval_results_path
                else None
            )
        except Exception as exc:
            print(f"SWE-bench error: {exc}", file=sys.stderr)
            return 1

        print(f"SWE-bench benchmark run: {report.run_id}")
        print(
            "Resolved: "
            f"{report.resolved_tasks}/{report.total_tasks} "
            f"({report.resolved_rate:.1%})"
        )
        print(f"Predictions: {predictions.predictions_path}")
        if evaluation_result is not None:
            print(f"Evaluator exit: {evaluation_result.exit_code}")
            print(f"Evaluator results: {evaluation_result.results_path}")
        if evaluation_artifact_path is not None:
            print(f"Evaluator artifact: {evaluation_artifact_path}")
        if annotated_report_path is not None:
            print(f"Annotated report: {annotated_report_path}")
        print(f"Report: {report.report_path}")
        if evaluation_result is not None and not evaluation_result.passed:
            return 1
        return 0 if report.failed_tasks == 0 else 1

    if args.prompt or fix_from_verifier:
        try:
            if fix_from_verifier:
                initial_result = _run_initial_fix_verifier(config)
                if initial_result.passed:
                    print("CodeAgent-X fix: verifier already passes; no changes needed.")
                    print(f"Verify: {config.verification_command}")
                    print(f"Workspace: {Path(config.workspace_root).resolve()}")
                    return 0
                args.prompt = _build_fix_prompt(
                    args.prompt,
                    command=config.verification_command or "",
                    result=initial_result,
                )
            agent = AgentLoop(config=config, registry=registry)
            if one_shot_run:
                print(f"CodeAgent-X run: {args.prompt}")
                print(f"Workspace: {Path(config.workspace_root).resolve()}")
                if config.verification_command:
                    print(f"Verify: {config.verification_command}")
                if args.branch is not None:
                    branch = _resolve_branch_name(args.branch)
                    _git_checked(["git", "checkout", "-b", branch], cwd=Path(config.workspace_root).resolve())
                    print(f"Branch: {branch}")
                print()
            agent.run(args.prompt)
            if one_shot_run and args.commit:
                commit_created = _commit_after_successful_run(
                    agent,
                    config,
                    message=args.commit_message or _default_commit_message(args.prompt),
                )
                if args.pr and commit_created:
                    pr_url = _push_and_create_pull_request(
                        config,
                        remote=args.remote,
                        base=args.base,
                        title=args.pr_title or _default_pr_title(args.prompt),
                        body=args.pr_body or _default_pr_body(args.prompt, agent),
                    )
                    print(f"Pull request: {pr_url}")
                elif args.pr:
                    print("Pull request: skipped, no commit was created")
            if one_shot_run:
                _print_run_summary(agent, config)
            print()
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        return 0

    agent = AgentLoop(config=config, registry=registry)
    run_interactive(agent)
    return 0


def _run_initial_fix_verifier(config: Config):
    command = config.verification_command
    if not command:
        raise RuntimeError("fix requires a verification command")
    print(f"CodeAgent-X fix: running verifier first: {command}")
    return LocalSandboxRunner().run(
        command,
        spec=SandboxSpec(
            workspace_root=config.workspace_root,
            cwd=config.workspace_root,
            timeout_seconds=config.verification_timeout_seconds,
            max_output_chars=config.max_output_chars,
            enforce_workspace=config.enforce_workspace_paths,
        ),
    )


def _build_fix_prompt(user_prompt: str | None, *, command: str, result) -> str:
    context = " ".join((user_prompt or "").split())
    if not context:
        context = "Fix the failing verification command."
    stdout = _clip_for_prompt(result.stdout)
    stderr = _clip_for_prompt(result.stderr)
    return (
        f"{context}\n\n"
        "The verification command failed before the agent started. "
        "Use this failure output as the primary debugging context, inspect the repository, "
        "make the smallest safe fix, and rerun the configured verifier.\n\n"
        f"Command: {command}\n"
        f"Exit code: {result.exit_code}\n\n"
        "STDOUT:\n"
        f"```text\n{stdout}\n```\n\n"
        "STDERR:\n"
        f"```text\n{stderr}\n```"
    )


def _clip_for_prompt(text: str, *, limit: int = 12000) -> str:
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    return text[-limit:] + f"\n... clipped {omitted} earlier chars"


def _print_run_summary(agent: AgentLoop, config: Config) -> None:
    """Print a compact developer-facing summary after a one-shot local run."""

    state = getattr(agent, "last_state", None)
    print("\n--- CodeAgent-X summary ---")
    if state is not None:
        print(f"Task: {state.task_id}")
        verification = getattr(state, "verification_report", None)
        if isinstance(verification, dict):
            status = verification.get("status", "unknown")
            summary = verification.get("summary", "")
            print(f"Verification: {status}" + (f" - {summary}" if summary else ""))
        trajectory_dir = config.trajectory_dir
        if trajectory_dir:
            print(f"Trajectory dir: {trajectory_dir}")

    workspace = Path(config.workspace_root).resolve()
    status = _git_command(["git", "status", "--short"], cwd=workspace)
    if status is not None:
        changed = [line for line in status.splitlines() if line.strip()]
        print(f"Changed files: {len(changed)}")
        for line in changed[:20]:
            print(f"  {line}")
        if len(changed) > 20:
            print(f"  ... {len(changed) - 20} more")

    diff = _git_command(["git", "diff", "--stat"], cwd=workspace)
    if diff:
        print("\nDiff stat:")
        print(diff)


def _commit_after_successful_run(agent: AgentLoop, config: Config, *, message: str) -> bool:
    state = getattr(agent, "last_state", None)
    verification = getattr(state, "verification_report", None)
    if isinstance(verification, dict) and verification.get("status") == "failed":
        raise RuntimeError("refusing to commit because verification failed")

    workspace = Path(config.workspace_root).resolve()
    status = _git_command(["git", "status", "--short"], cwd=workspace)
    if not status:
        print("Commit: skipped, no local changes")
        return False

    _git_checked(["git", "add", "-A"], cwd=workspace)
    _git_checked(["git", "commit", "-m", message], cwd=workspace)
    print(f"Commit: {message}")
    return True


def _push_and_create_pull_request(
    config: Config,
    *,
    remote: str,
    base: str,
    title: str,
    body: str,
) -> str:
    workspace = Path(config.workspace_root).resolve()
    branch = _git_checked(["git", "branch", "--show-current"], cwd=workspace).strip()
    if not branch:
        raise RuntimeError("cannot create PR from a detached HEAD")

    repository = os.getenv("CODEAGENTX_GITHUB_REPOSITORY") or _repository_from_remote(
        _git_checked(["git", "remote", "get-url", remote], cwd=workspace)
    )
    token = os.getenv("CODEAGENTX_GITHUB_TOKEN")
    if not token:
        raise RuntimeError("CODEAGENTX_GITHUB_TOKEN is required for --pr")

    _git_checked(["git", "push", "-u", remote, branch], cwd=workspace)
    return _create_github_pull_request(
        repository=repository,
        token=token,
        base=base,
        head=branch,
        title=title,
        body=body,
    )


def _resolve_branch_name(value: str | None) -> str:
    if value:
        return value
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"codeagentx/local-{timestamp}"


def _default_commit_message(prompt: str) -> str:
    normalized = " ".join(prompt.split())
    if not normalized:
        return "Apply CodeAgent-X changes"
    if len(normalized) > 72:
        normalized = normalized[:69].rstrip() + "..."
    return f"CodeAgent-X: {normalized}"


def _default_pr_title(prompt: str) -> str:
    normalized = " ".join(prompt.split())
    if not normalized:
        return "CodeAgent-X changes"
    if len(normalized) > 80:
        normalized = normalized[:77].rstrip() + "..."
    return normalized[0].upper() + normalized[1:]


def _default_pr_body(prompt: str, agent: AgentLoop) -> str:
    state = getattr(agent, "last_state", None)
    task_id = getattr(state, "task_id", None)
    verification = getattr(state, "verification_report", None)
    lines = [
        "Created by CodeAgent-X local run.",
        "",
        f"Prompt: {prompt}",
    ]
    if task_id:
        lines.append(f"Task: {task_id}")
    if isinstance(verification, dict):
        status = verification.get("status", "unknown")
        summary = verification.get("summary", "")
        lines.append(f"Verification: {status}" + (f" - {summary}" if summary else ""))
    return "\n".join(lines)


def _repository_from_remote(remote_url: str) -> str:
    value = remote_url.strip()
    patterns = [
        r"github\.com[:/](?P<repo>[^/]+/[^/.]+)(?:\.git)?$",
        r"github\.com[:/](?P<repo>[^/]+/[^/]+?)(?:\.git)?(?:/)?$",
    ]
    for pattern in patterns:
        match = re.search(pattern, value)
        if match:
            return match.group("repo")
    raise RuntimeError(
        "could not infer GitHub repository from remote; set CODEAGENTX_GITHUB_REPOSITORY=owner/repo"
    )


def _create_github_pull_request(
    *,
    repository: str,
    token: str,
    base: str,
    head: str,
    title: str,
    body: str,
) -> str:
    api_base = os.getenv("CODEAGENTX_GITHUB_API_BASE_URL", "https://api.github.com").rstrip("/")
    payload = json.dumps({
        "title": title,
        "head": head,
        "base": base,
        "body": body,
    }).encode("utf-8")
    http_request = request.Request(
        f"{api_base}/repos/{repository}/pulls",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "CodeAgent-X",
        },
    )
    try:
        with request.urlopen(http_request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub PR creation failed with HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"GitHub PR creation failed: {exc}") from exc

    url = data.get("html_url")
    if not isinstance(url, str) or not url:
        raise RuntimeError("GitHub PR creation response did not include html_url")
    return url


def _git_checked(command: list[str], *, cwd: Path) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"git command failed: {' '.join(command)}: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"git command failed: {' '.join(command)}" + (f": {detail}" if detail else ""))
    return result.stdout.strip()


def _git_command(command: list[str], *, cwd: Path) -> str | None:
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _filter_benchmark_tasks(tasks, *, task_ids: list[str], limit: int | None):
    selected = list(tasks)
    if task_ids:
        wanted = set(task_ids)
        selected = [task for task in selected if task.task_id in wanted]
        missing = sorted(wanted - {task.task_id for task in selected})
        if missing:
            raise ValueError(f"unknown benchmark task id(s): {', '.join(missing)}")
    if limit is not None:
        if limit <= 0:
            raise ValueError("--benchmark-limit must be greater than 0")
        selected = selected[:limit]
    if not selected:
        raise ValueError("benchmark task filter selected no tasks")
    return selected


def _filter_benchmark_variants(variants, *, variant_names: list[str]):
    selected = list(variants)
    if variant_names:
        wanted = set(variant_names)
        selected = [variant for variant in selected if variant.name in wanted]
        missing = sorted(wanted - {variant.name for variant in selected})
        if missing:
            raise ValueError(f"unknown benchmark variant(s): {', '.join(missing)}")
    if not selected:
        raise ValueError("benchmark variant filter selected no variants")
    return selected


def _load_swebench_benchmark_tasks(args):
    from .evaluation import SWEbenchWorkspaceProvisioner, load_swebench_tasks

    swebench_tasks = load_swebench_tasks(
        args.swebench,
        task_ids=args.benchmark_task_id or None,
        limit=args.benchmark_limit,
    )
    provisioner = SWEbenchWorkspaceProvisioner(
        workspaces_root=args.swebench_workspaces_root,
        repo_cache_root=(
            None
            if args.swebench_no_repo_cache
            else args.swebench_repo_cache_root
        ),
        repo_url_template=args.swebench_repo_url_template,
        timeout_seconds=args.swebench_git_timeout,
        overwrite_existing=not args.swebench_no_overwrite,
        refresh_cache=args.swebench_refresh_cache,
        update_submodules=args.swebench_update_submodules,
    )
    return provisioner.prepare_benchmark_tasks(
        swebench_tasks,
        verification_command=args.verify_command,
        setup_command=args.swebench_setup_command,
    )


def _load_swebench_manifest_tasks(args):
    from .evaluation import load_swebench_tasks

    return load_swebench_tasks(
        args.swebench,
        task_ids=args.benchmark_task_id or None,
        limit=args.benchmark_limit,
    )


def _write_swebench_manifest_for_tasks(tasks, args):
    from .evaluation import write_swebench_task_manifest

    output_path = (
        args.swebench_manifest_output
        or str(Path(args.benchmark_output_dir).expanduser() / "swebench_task_manifest.json")
    )
    return write_swebench_task_manifest(
        tasks,
        output_path,
        source_path=args.swebench,
        selected_task_ids=args.benchmark_task_id or None,
        limit=args.benchmark_limit,
        workspaces_root=args.swebench_workspaces_root,
    )


def _write_swebench_preflight_for_tasks(tasks, args):
    output_path = (
        args.swebench_preflight_output
        or str(Path(args.benchmark_output_dir).expanduser() / "swebench_preflight.json")
    )
    return _write_swebench_preflight_to_path(tasks, args, output_path)


def _write_swebench_preflight_to_path(
    tasks,
    args,
    output_path: str | Path,
    *,
    source_path: str | Path | None = None,
    memory_policy: str | None = None,
):
    from .evaluation import write_swebench_preflight_report

    return write_swebench_preflight_report(
        tasks,
        output_path,
        source_path=source_path if source_path is not None else args.swebench,
        selected_task_ids=args.benchmark_task_id or None,
        limit=args.benchmark_limit,
        provider=args.provider,
        model=args.model,
        memory_policy=memory_policy or args.benchmark_memory_policy,
        evaluate_requested=args.swebench_evaluate,
        verification_sandbox=args.verification_sandbox,
        benchmark_output_dir=args.benchmark_output_dir,
        workspaces_root=args.swebench_workspaces_root,
        repo_cache_root=args.swebench_repo_cache_root,
        repo_cache_enabled=not args.swebench_no_repo_cache,
        python_executable=args.swebench_eval_python_executable or sys.executable,
        evaluator_command_prefix=_split_command_prefix(args.swebench_eval_command_prefix),
        docker_binary="docker",
        docker_lifecycle_image=args.swebench_docker_lifecycle_image,
    )


def _run_swebench_auto_preflight_if_needed(args):
    if args.swebench_no_auto_preflight:
        return None
    if not (args.swebench_evaluate or args.verification_sandbox == "docker"):
        return None
    tasks = _load_swebench_manifest_tasks(args)
    output_path = (
        args.swebench_preflight_output
        or str(Path(args.benchmark_output_dir).expanduser() / "swebench_auto_preflight.json")
    )
    return _write_swebench_preflight_to_path(tasks, args, output_path)


def _run_swebench_report_auto_preflight_if_needed(report, args):
    if args.swebench_no_auto_preflight:
        return None
    if not args.swebench_evaluate:
        return None
    tasks = _load_swebench_report_tasks(report, args)
    output_path = (
        args.swebench_preflight_output
        or str(Path(report.output_dir).expanduser() / "swebench_report_auto_preflight.json")
    )
    return _write_swebench_preflight_to_path(
        tasks,
        args,
        output_path,
        source_path=report.report_path,
        memory_policy=_swebench_report_memory_policy(
            report,
            fallback=args.benchmark_memory_policy,
        ),
    )


def _load_swebench_report_tasks(report, args):
    from .evaluation import SWEbenchTaskSpec

    report_file = Path(report.report_path).expanduser()
    payload = json.loads(report_file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("benchmark report JSON must be an object")

    wanted = {str(item) for item in getattr(args, "benchmark_task_id", []) or []}
    matched: set[str] = set()
    tasks: list[SWEbenchTaskSpec] = []
    raw_tasks = payload.get("tasks")
    for raw_task in raw_tasks if isinstance(raw_tasks, list) else []:
        if not isinstance(raw_task, dict):
            continue
        task_id = str(raw_task.get("task_id") or raw_task.get("id") or "")
        metadata = raw_task.get("metadata")
        if not isinstance(metadata, dict):
            continue
        swebench = metadata.get("swebench")
        if not isinstance(swebench, dict):
            continue
        instance_id = str(swebench.get("instance_id") or task_id)
        if wanted and task_id not in wanted and instance_id not in wanted:
            continue
        if task_id in wanted:
            matched.add(task_id)
        if instance_id in wanted:
            matched.add(instance_id)
        tasks.append(
            SWEbenchTaskSpec(
                instance_id=instance_id,
                repo=str(swebench.get("repo") or swebench.get("repository") or ""),
                base_commit=str(swebench.get("base_commit") or swebench.get("commit") or ""),
                problem_statement=str(
                    swebench.get("problem_statement")
                    or raw_task.get("goal")
                    or "Report-derived SWE-bench task."
                ),
                fail_to_pass=_report_string_list(
                    swebench.get("FAIL_TO_PASS", swebench.get("fail_to_pass"))
                ),
                pass_to_pass=_report_string_list(
                    swebench.get("PASS_TO_PASS", swebench.get("pass_to_pass"))
                ),
                version=(
                    None
                    if swebench.get("version") in (None, "")
                    else str(swebench.get("version"))
                ),
                environment=dict(swebench.get("environment") or {}),
                metadata={
                    "source_report_path": str(report_file),
                    "source_report_task_id": task_id,
                    **(
                        dict(swebench.get("metadata"))
                        if isinstance(swebench.get("metadata"), dict)
                        else {}
                    ),
                },
            )
        )

    missing = sorted(wanted - matched)
    if missing:
        raise ValueError(f"unknown SWE-bench report task id(s): {', '.join(missing)}")
    limit = getattr(args, "benchmark_limit", None)
    if limit is not None:
        if limit <= 0:
            raise ValueError("--benchmark-limit must be greater than 0")
        tasks = tasks[:limit]
    if not tasks:
        raise ValueError("benchmark report contains no SWE-bench tasks")
    for task in tasks:
        if not task.repo:
            raise ValueError(f"SWE-bench report task {task.instance_id!r} is missing repo")
        if not task.base_commit:
            raise ValueError(
                f"SWE-bench report task {task.instance_id!r} is missing base_commit"
            )
    return tasks


def _swebench_report_memory_policy(report, *, fallback: str) -> str:
    report_file = Path(report.report_path).expanduser()
    payload = json.loads(report_file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return fallback
    value = payload.get("memory_policy")
    if isinstance(value, dict) and value.get("policy") not in (None, ""):
        return str(value["policy"])
    if isinstance(value, str) and value.strip():
        return value
    return fallback


def _report_string_list(value) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("["):
            try:
                decoded = json.loads(stripped)
            except json.JSONDecodeError:
                return [value]
            if isinstance(decoded, list):
                return [str(item) for item in decoded]
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple):
        return [str(item) for item in value]
    return [str(value)]


def _load_swebench_report_reference(report_path: str | Path):
    report_file = Path(report_path).expanduser()
    payload = json.loads(report_file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("benchmark report JSON must be an object")

    output_dir = payload.get("output_dir")
    return argparse.Namespace(
        report_path=str(report_file),
        output_dir=(
            str(Path(str(output_dir)).expanduser())
            if output_dir
            else str(report_file.parent)
        ),
        run_id=str(
            payload.get("run_id")
            or report_file.parent.name
            or "codeagentx-swebench-report"
        ),
    )


def _write_swebench_predictions_for_report(report, args):
    from .evaluation import write_swebench_predictions_from_report

    output_path = (
        args.swebench_predictions_output
        or str(report.output_dir) + "/swebench_predictions.jsonl"
    )
    return write_swebench_predictions_from_report(
        report.report_path,
        output_path,
        model_name_or_path=_swebench_model_name(args),
        include_empty_patches=not args.swebench_skip_empty_patches,
        task_ids=getattr(args, "benchmark_task_id", None) or None,
        limit=getattr(args, "benchmark_limit", None),
    )

def _write_swebench_repair_benchmark_for_report(report, args):
    from .evaluation import write_swebench_repair_benchmark_spec

    return write_swebench_repair_benchmark_spec(
        report.report_path,
        args.swebench_repair_output,
        task_ids=getattr(args, "benchmark_task_id", None) or None,
        limit=getattr(args, "benchmark_limit", None),
        include_resolved=args.swebench_repair_include_resolved,
        max_failure_excerpt_chars=args.swebench_repair_max_excerpt_chars,
        max_previous_patch_chars=args.swebench_repair_max_patch_chars,
    )


def _run_swebench_official_evaluator(report, predictions, args):
    from .evaluation import SWEbenchEvaluatorConfig, run_swebench_evaluation

    command_prefix = _split_command_prefix(args.swebench_eval_command_prefix)
    config = SWEbenchEvaluatorConfig(
        dataset_name=args.swebench_eval_dataset,
        split=args.swebench_eval_split,
        run_id=args.swebench_eval_run_id or report.run_id,
        max_workers=args.swebench_eval_max_workers,
        timeout_seconds=args.swebench_eval_timeout,
        cache_level=args.swebench_eval_cache_level,
        clean=args.swebench_eval_clean,
        namespace=(
            None
            if args.swebench_eval_no_namespace
            else args.swebench_eval_namespace
        ),
        report_dir=args.swebench_eval_report_dir,
        python_executable=args.swebench_eval_python_executable or sys.executable,
        command_prefix=command_prefix,
        posix_paths=bool(command_prefix) and sys.platform.startswith("win"),
    )
    return run_swebench_evaluation(
        predictions.predictions_path,
        config=config,
        instance_ids=list(predictions.instance_ids),
        process_timeout_seconds=args.swebench_eval_process_timeout,
    )


def _write_swebench_evaluation_result_artifact(report, evaluation_result, args) -> Path:
    output_path = (
        args.swebench_eval_artifact_output
        or str(Path(report.output_dir).expanduser() / "swebench_evaluation_result.json")
    )
    output = Path(output_path).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(evaluation_result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output


def _split_command_prefix(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        return shlex.split(value)
    except ValueError as exc:
        raise ValueError(f"invalid --swebench-eval-command-prefix: {exc}") from exc


def _annotate_swebench_report_if_available(report, evaluation_result, args):
    from .evaluation import annotate_benchmark_report_with_swebench_evaluation

    raw_results_path = (
        args.swebench_eval_results_path
        or (evaluation_result.results_path if evaluation_result is not None else None)
    )
    if not raw_results_path:
        return None
    results_path = Path(raw_results_path)
    if not results_path.exists():
        return None
    return annotate_benchmark_report_with_swebench_evaluation(
        report.report_path,
        results_path,
        output_path=args.swebench_annotated_report_output,
    )


def _swebench_model_name(args) -> str:
    if args.swebench_model_name:
        return args.swebench_model_name
    return f"codeagentx/{args.provider}/{args.model}"


def _benchmark_final_config_overrides(args) -> dict[str, object]:
    overrides: dict[str, object] = {}
    if getattr(args, "no_sandbox_artifacts", False):
        overrides["enable_sandbox_artifacts"] = False
        overrides["sandbox_artifact_dir"] = None
    return overrides


def _configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="replace")
        except (AttributeError, ValueError):
            continue


if __name__ == "__main__":
    raise SystemExit(main())
