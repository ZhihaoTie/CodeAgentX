"""SWE-bench preflight checks before expensive benchmark runs."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from .swebench import (
    DEFAULT_SWEBENCH_REPO_CACHE_ROOT,
    DEFAULT_SWEBENCH_WORKSPACES_ROOT,
    SWEbenchTaskSpec,
    build_swebench_task_manifest,
)


SWEBENCH_PREFLIGHT_SCHEMA_VERSION = "codeagentx.swebench_preflight.v1"
SWEBENCH_PREFLIGHT_STATUSES = {"pass", "warn", "fail"}
DEFAULT_SWEBENCH_DOCKER_LIFECYCLE_IMAGE = "python:3.12-slim"

_DOCKER_LIFECYCLE_PYTHON = """
import sys
import uuid

import docker

image = sys.argv[1]
name = "codeagentx-preflight-" + uuid.uuid4().hex[:12]
container = None
client = docker.from_env()
client.ping()
try:
    container = client.containers.create(
        image=image,
        command=["python", "-c", "print('codeagentx_docker_lifecycle=ok')"],
        detach=True,
        name=name,
    )
    container.start()
    result = container.wait(timeout=30)
    logs = container.logs(stdout=True, stderr=True).decode("utf-8", "replace")
    if logs:
        print(logs, end="")
    status_code = int(result.get("StatusCode", 1))
    if status_code != 0:
        raise SystemExit(status_code)
finally:
    if container is not None:
        container.remove(force=True)
print("codeagentx_docker_lifecycle=ok")
""".strip()

ExecutableResolver = Callable[[str], str | None]
ImportChecker = Callable[[str], bool]
CommandRunner = Callable[[list[str], int], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class SWEbenchPreflightCheck:
    """One preflight check result."""

    name: str
    status: str
    message: str
    required: bool = False
    command: list[str] = field(default_factory=list)
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status != "fail"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "required": self.required,
            "command": list(self.command),
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class SWEbenchPreflightReport:
    """Structured preflight report for a selected SWE-bench run."""

    source_path: str | None
    task_count: int
    task_ids: list[str]
    provider: str
    model: str
    memory_policy: str
    evaluate_requested: bool
    verification_sandbox: str
    benchmark_output_dir: str
    report_path: str | None = None
    checks: list[SWEbenchPreflightCheck] = field(default_factory=list)
    task_manifest: Mapping[str, Any] = field(default_factory=dict)

    @property
    def failure_count(self) -> int:
        return sum(1 for check in self.checks if check.status == "fail")

    @property
    def warning_count(self) -> int:
        return sum(1 for check in self.checks if check.status == "warn")

    @property
    def passed(self) -> bool:
        return self.failure_count == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SWEBENCH_PREFLIGHT_SCHEMA_VERSION,
            "source_path": self.source_path,
            "report_path": self.report_path,
            "task_count": self.task_count,
            "task_ids": list(self.task_ids),
            "provider": self.provider,
            "model": self.model,
            "memory_policy": self.memory_policy,
            "evaluate_requested": self.evaluate_requested,
            "verification_sandbox": self.verification_sandbox,
            "benchmark_output_dir": self.benchmark_output_dir,
            "summary": {
                "passed": self.passed,
                "failure_count": self.failure_count,
                "warning_count": self.warning_count,
                "check_count": len(self.checks),
            },
            "checks": [check.to_dict() for check in self.checks],
            "task_manifest": dict(self.task_manifest),
        }


def build_swebench_preflight_report(
    tasks: list[SWEbenchTaskSpec],
    *,
    source_path: str | Path | None = None,
    selected_task_ids: list[str] | None = None,
    limit: int | None = None,
    provider: str = "anthropic",
    model: str = "",
    memory_policy: str = "shared",
    evaluate_requested: bool = False,
    verification_sandbox: str = "local",
    benchmark_output_dir: str | Path = ".codeagentx/benchmarks",
    workspaces_root: str | Path = DEFAULT_SWEBENCH_WORKSPACES_ROOT,
    repo_cache_root: str | Path | None = DEFAULT_SWEBENCH_REPO_CACHE_ROOT,
    repo_cache_enabled: bool = True,
    preflight_output_path: str | Path | None = None,
    python_executable: str = sys.executable,
    evaluator_command_prefix: list[str] | None = None,
    docker_binary: str = "docker",
    docker_lifecycle_image: str = DEFAULT_SWEBENCH_DOCKER_LIFECYCLE_IMAGE,
    env: Mapping[str, str] | None = None,
    executable_resolver: ExecutableResolver | None = None,
    import_checker: ImportChecker | None = None,
    command_runner: CommandRunner | None = None,
) -> SWEbenchPreflightReport:
    """Build a preflight report without provisioning workspaces or running models."""

    if not tasks:
        raise ValueError("cannot build a SWE-bench preflight report for zero tasks")

    run_env = env if env is not None else os.environ
    resolver = executable_resolver or shutil.which
    checker = import_checker or _module_available
    runner = command_runner or _run_command
    command_prefix = list(evaluator_command_prefix or [])
    manifest = build_swebench_task_manifest(
        tasks,
        source_path=source_path,
        selected_task_ids=selected_task_ids,
        limit=limit,
        workspaces_root=workspaces_root,
    )

    docker_required = evaluate_requested or verification_sandbox == "docker"
    checks = [
        _task_selection_check(manifest),
        _prompt_leakage_check(manifest),
        _git_check(resolver=resolver, command_runner=runner),
        _docker_check(
            docker_binary=docker_binary,
            required=docker_required,
            resolver=resolver,
            command_runner=runner,
        ),
    ]
    if docker_required:
        checks.append(
            _docker_container_lifecycle_check(
                docker_binary=docker_binary,
                docker_lifecycle_image=docker_lifecycle_image,
                python_executable=python_executable,
                command_prefix=command_prefix,
                resolver=resolver,
                command_runner=runner,
            )
        )
    checks.extend([
        _swebench_harness_check(
            required=evaluate_requested,
            python_executable=python_executable,
            command_prefix=command_prefix,
            import_checker=checker,
            command_runner=runner,
        ),
        _model_config_check(provider=provider, env=run_env),
        _memory_policy_check(memory_policy=memory_policy, evaluate_requested=evaluate_requested),
        _path_config_check(
            benchmark_output_dir=benchmark_output_dir,
            workspaces_root=workspaces_root,
            repo_cache_root=repo_cache_root,
            repo_cache_enabled=repo_cache_enabled,
            preflight_output_path=preflight_output_path,
        ),
        _verification_check(
            verification_sandbox=verification_sandbox,
            evaluate_requested=evaluate_requested,
        ),
        _python_check(
            python_executable=python_executable,
            command_prefix=command_prefix,
            command_runner=runner,
        ),
    ])

    return SWEbenchPreflightReport(
        source_path=str(source_path) if source_path is not None else None,
        report_path=str(preflight_output_path) if preflight_output_path is not None else None,
        task_count=manifest.task_count,
        task_ids=manifest.task_ids,
        provider=provider,
        model=model,
        memory_policy=memory_policy,
        evaluate_requested=evaluate_requested,
        verification_sandbox=verification_sandbox,
        benchmark_output_dir=str(benchmark_output_dir),
        checks=checks,
        task_manifest=manifest.to_dict(),
    )


def write_swebench_preflight_report(
    tasks: list[SWEbenchTaskSpec],
    output_path: str | Path,
    **kwargs: Any,
) -> SWEbenchPreflightReport:
    """Write a SWE-bench preflight report JSON artifact."""

    output = Path(output_path).expanduser()
    report = build_swebench_preflight_report(
        tasks,
        preflight_output_path=output,
        **kwargs,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def _task_selection_check(manifest: Any) -> SWEbenchPreflightCheck:
    return SWEbenchPreflightCheck(
        name="task_selection",
        status="pass",
        required=True,
        message=f"Loaded {manifest.task_count} SWE-bench task(s).",
        details={
            "task_count": manifest.task_count,
            "repositories": manifest.repositories,
            "task_ids": manifest.task_ids,
        },
    )


def _prompt_leakage_check(manifest: Any) -> SWEbenchPreflightCheck:
    if manifest.prompt_leakage_count:
        return SWEbenchPreflightCheck(
            name="prompt_leakage_guard",
            status="fail",
            required=True,
            message="One or more grader test targets appear in the agent prompt.",
            details={
                "prompt_leakage_task_count": manifest.prompt_leakage_count,
                "leaking_task_ids": [
                    entry.instance_id
                    for entry in manifest.entries
                    if entry.prompt_contains_grader_tests
                ],
            },
        )
    return SWEbenchPreflightCheck(
        name="prompt_leakage_guard",
        status="pass",
        required=True,
        message="FAIL_TO_PASS and PASS_TO_PASS targets are hidden from the agent prompt.",
        details={"prompt_leakage_task_count": 0},
    )


def _git_check(
    *,
    resolver: ExecutableResolver,
    command_runner: CommandRunner,
) -> SWEbenchPreflightCheck:
    git_path = resolver("git")
    if not git_path:
        return SWEbenchPreflightCheck(
            name="git_available",
            status="fail",
            required=True,
            message="git is required to provision SWE-bench workspaces.",
        )
    return _version_command_check(
        name="git_available",
        command=[git_path, "--version"],
        required=True,
        success_message="git is available for workspace provisioning.",
        failure_message="git exists but version check failed.",
        command_runner=command_runner,
        details={"executable": git_path},
    )


def _docker_check(
    *,
    docker_binary: str,
    required: bool,
    resolver: ExecutableResolver,
    command_runner: CommandRunner,
) -> SWEbenchPreflightCheck:
    docker_path = resolver(docker_binary)
    if not docker_path:
        return SWEbenchPreflightCheck(
            name="docker_available",
            status="fail" if required else "warn",
            required=required,
            message=(
                "Docker is required for the requested official evaluation or docker sandbox."
                if required
                else "Docker is not available; official evaluation or docker sandbox runs will fail if enabled."
            ),
            details={"docker_binary": docker_binary},
        )
    return _version_command_check(
        name="docker_available",
        command=[docker_path, "--version"],
        required=required,
        success_message="Docker CLI is available.",
        failure_message="Docker CLI exists but version check failed.",
        command_runner=command_runner,
        details={"executable": docker_path},
        warn_if_optional=True,
    )


def _docker_container_lifecycle_check(
    *,
    docker_binary: str,
    docker_lifecycle_image: str,
    python_executable: str,
    command_prefix: list[str],
    resolver: ExecutableResolver,
    command_runner: CommandRunner,
) -> SWEbenchPreflightCheck:
    image = docker_lifecycle_image.strip()
    if not image:
        return SWEbenchPreflightCheck(
            name="docker_container_lifecycle",
            status="fail",
            required=True,
            message="Docker lifecycle smoke image is empty.",
            details={"probe_image": docker_lifecycle_image},
        )

    if command_prefix:
        command = [
            *command_prefix,
            python_executable,
            "-c",
            _DOCKER_LIFECYCLE_PYTHON,
            image,
        ]
        success_message = (
            "Docker daemon can create, run, wait for, and remove a probe "
            "container through the evaluator command prefix."
        )
        failure_message = (
            "Docker container lifecycle check failed through the evaluator "
            "command prefix."
        )
        details = {
            "probe_image": image,
            "command_prefix": list(command_prefix),
            "uses_python_docker_sdk": True,
        }
    else:
        docker_path = resolver(docker_binary)
        if not docker_path:
            return SWEbenchPreflightCheck(
                name="docker_container_lifecycle",
                status="fail",
                required=True,
                message="Docker is required for the container lifecycle check.",
                details={"docker_binary": docker_binary, "probe_image": image},
            )
        command = [
            docker_path,
            "run",
            "--rm",
            image,
            "python",
            "-c",
            "print('codeagentx_docker_lifecycle=ok')",
        ]
        success_message = (
            "Docker daemon can create, run, and remove a probe container."
        )
        failure_message = "Docker container lifecycle check failed."
        details = {
            "probe_image": image,
            "executable": docker_path,
            "uses_python_docker_sdk": False,
        }

    try:
        result = command_runner(command, 120)
    except OSError as exc:
        return SWEbenchPreflightCheck(
            name="docker_container_lifecycle",
            status="fail",
            required=True,
            message=f"{failure_message} {exc.__class__.__name__}: {exc}",
            command=command,
            details=details,
        )
    passed = result.returncode == 0
    return SWEbenchPreflightCheck(
        name="docker_container_lifecycle",
        status="pass" if passed else "fail",
        required=True,
        message=success_message if passed else failure_message,
        command=command,
        exit_code=result.returncode,
        stdout=_truncate(result.stdout),
        stderr=_truncate(result.stderr),
        details=details,
    )


def _swebench_harness_check(
    *,
    required: bool,
    python_executable: str,
    command_prefix: list[str],
    import_checker: ImportChecker,
    command_runner: CommandRunner,
) -> SWEbenchPreflightCheck:
    if command_prefix:
        command = [
            *command_prefix,
            python_executable,
            "-c",
            "import swebench.harness.run_evaluation; print('swebench_harness=ok')",
        ]
        try:
            result = command_runner(command, 60)
        except OSError as exc:
            return SWEbenchPreflightCheck(
                name="swebench_harness_available",
                status="fail" if required else "warn",
                required=required,
                message=(
                    "SWE-bench evaluator command prefix failed before harness import: "
                    f"{exc.__class__.__name__}: {exc}"
                ),
                command=command,
                details={"command_prefix": list(command_prefix)},
            )
        passed = result.returncode == 0
        return SWEbenchPreflightCheck(
            name="swebench_harness_available",
            status="pass" if passed else ("fail" if required else "warn"),
            required=required,
            message=(
                "swebench.harness.run_evaluation is importable through evaluator command prefix."
                if passed
                else "The evaluator command prefix could not import swebench.harness.run_evaluation."
            ),
            command=command,
            exit_code=result.returncode,
            stdout=_truncate(result.stdout),
            stderr=_truncate(result.stderr),
            details={"command_prefix": list(command_prefix)},
        )

    available = import_checker("swebench.harness.run_evaluation")
    if available:
        return SWEbenchPreflightCheck(
            name="swebench_harness_available",
            status="pass",
            required=required,
            message="swebench.harness.run_evaluation is importable.",
        )
    return SWEbenchPreflightCheck(
        name="swebench_harness_available",
        status="fail" if required else "warn",
        required=required,
        message=(
            "The official swebench harness is required for --swebench-evaluate."
            if required
            else "The official swebench harness is not importable; evaluator mode will fail if enabled."
        ),
    )


def _model_config_check(
    *,
    provider: str,
    env: Mapping[str, str],
) -> SWEbenchPreflightCheck:
    normalized = provider.strip().lower()
    if normalized == "mock":
        return SWEbenchPreflightCheck(
            name="model_provider_config",
            status="pass",
            required=True,
            message="Mock provider does not require an API key.",
            details={"provider": provider},
        )
    key_by_provider = {
        "anthropic": "ANTHROPIC_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
    }
    key_name = key_by_provider.get(normalized)
    if key_name is None:
        return SWEbenchPreflightCheck(
            name="model_provider_config",
            status="fail",
            required=True,
            message=f"Unknown model provider: {provider}.",
            details={"provider": provider},
        )
    if env.get(key_name):
        return SWEbenchPreflightCheck(
            name="model_provider_config",
            status="pass",
            required=True,
            message=f"{key_name} is configured.",
            details={"provider": provider, "required_env": key_name},
        )
    return SWEbenchPreflightCheck(
        name="model_provider_config",
        status="fail",
        required=True,
        message=f"{key_name} is required for provider {provider}.",
        details={"provider": provider, "required_env": key_name},
    )


def _memory_policy_check(
    *,
    memory_policy: str,
    evaluate_requested: bool,
) -> SWEbenchPreflightCheck:
    normalized = str(memory_policy).strip().lower()
    if normalized == "disabled":
        return SWEbenchPreflightCheck(
            name="benchmark_memory_policy",
            status="pass",
            required=True,
            message="Long-term memory is disabled for the benchmark run.",
            details={"memory_policy": normalized},
        )
    if evaluate_requested:
        return SWEbenchPreflightCheck(
            name="benchmark_memory_policy",
            status="fail",
            required=True,
            message="Official SWE-bench evaluation should use --benchmark-memory-policy disabled.",
            details={"memory_policy": normalized},
        )
    if normalized == "isolated":
        return SWEbenchPreflightCheck(
            name="benchmark_memory_policy",
            status="pass",
            required=False,
            message="Memory is isolated per task; no cross-task memory reuse.",
            details={"memory_policy": normalized},
        )
    return SWEbenchPreflightCheck(
        name="benchmark_memory_policy",
        status="warn",
        required=False,
        message="Shared memory permits cross-task reuse; use disabled for public SWE-bench scores.",
        details={"memory_policy": normalized},
    )


def _path_config_check(
    *,
    benchmark_output_dir: str | Path,
    workspaces_root: str | Path,
    repo_cache_root: str | Path | None,
    repo_cache_enabled: bool,
    preflight_output_path: str | Path | None,
) -> SWEbenchPreflightCheck:
    failures: list[str] = []
    paths = {
        "benchmark_output_dir": Path(benchmark_output_dir).expanduser(),
        "workspaces_root": Path(workspaces_root).expanduser(),
    }
    if repo_cache_enabled and repo_cache_root is not None:
        paths["repo_cache_root"] = Path(repo_cache_root).expanduser()
    for label, path in paths.items():
        if path.exists() and not path.is_dir():
            failures.append(f"{label} exists but is not a directory: {path}")

    if preflight_output_path is not None:
        output = Path(preflight_output_path).expanduser()
        if output.exists() and output.is_dir():
            failures.append(f"preflight_output_path is a directory: {output}")

    if failures:
        return SWEbenchPreflightCheck(
            name="path_configuration",
            status="fail",
            required=True,
            message="One or more configured output paths are invalid.",
            details={"failures": failures, "paths": {key: str(value) for key, value in paths.items()}},
        )
    return SWEbenchPreflightCheck(
        name="path_configuration",
        status="pass",
        required=True,
        message="Benchmark, workspace, and cache paths are structurally valid.",
        details={
            "paths": {key: str(value) for key, value in paths.items()},
            "preflight_output_path": (
                str(Path(preflight_output_path).expanduser())
                if preflight_output_path is not None
                else None
            ),
            "repo_cache_enabled": repo_cache_enabled,
        },
    )


def _verification_check(
    *,
    verification_sandbox: str,
    evaluate_requested: bool,
) -> SWEbenchPreflightCheck:
    if evaluate_requested:
        return SWEbenchPreflightCheck(
            name="verification_plan",
            status="pass",
            required=False,
            message="Official evaluator is requested; SWE-bench resolved will come from evaluator results.",
            details={"verification_sandbox": verification_sandbox},
        )
    return SWEbenchPreflightCheck(
        name="verification_plan",
        status="warn",
        required=False,
        message="Official evaluator is not requested; run output will only contain local benchmark evidence.",
        details={"verification_sandbox": verification_sandbox},
    )


def _python_check(
    *,
    python_executable: str,
    command_prefix: list[str],
    command_runner: CommandRunner,
) -> SWEbenchPreflightCheck:
    command = [*command_prefix, python_executable, "--version"]
    return _version_command_check(
        name="python_available",
        command=command,
        required=True,
        success_message=(
            "Python executable is available through evaluator command prefix."
            if command_prefix
            else "Python executable is available."
        ),
        failure_message="Python executable version check failed.",
        command_runner=command_runner,
        details={
            "executable": python_executable,
            "command_prefix": list(command_prefix),
        },
    )


def _version_command_check(
    *,
    name: str,
    command: list[str],
    required: bool,
    success_message: str,
    failure_message: str,
    command_runner: CommandRunner,
    details: Mapping[str, Any] | None = None,
    warn_if_optional: bool = False,
) -> SWEbenchPreflightCheck:
    try:
        result = command_runner(command, 10)
    except OSError as exc:
        return SWEbenchPreflightCheck(
            name=name,
            status="fail" if required else "warn",
            required=required,
            message=f"{failure_message} {exc.__class__.__name__}: {exc}",
            command=command,
            details=dict(details or {}),
        )
    passed = result.returncode == 0
    status = "pass" if passed else ("fail" if required else "warn")
    if warn_if_optional and not required and not passed:
        status = "warn"
    return SWEbenchPreflightCheck(
        name=name,
        status=status,
        required=required,
        message=success_message if passed else failure_message,
        command=command,
        exit_code=result.returncode,
        stdout=_truncate(result.stdout),
        stderr=_truncate(result.stderr),
        details=dict(details or {}),
    )


def _run_command(argv: list[str], timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_seconds,
    )


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def _truncate(value: object, max_chars: int = 2000) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return text[:max_chars] + f"\n... output truncated {omitted} chars"
