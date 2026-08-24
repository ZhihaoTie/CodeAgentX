"""Structured sandbox command execution."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping, Protocol
from uuid import uuid4

from codeagentx.security import WorkspacePathPolicy


DEFAULT_ENV_ALLOWLIST = (
    "COMSPEC",
    "HOME",
    "LANG",
    "LC_ALL",
    "PATH",
    "PATHEXT",
    "PYTHONIOENCODING",
    "PYTHONPATH",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "TMPDIR",
    "USERPROFILE",
    "WINDIR",
)


class SandboxCommandStatus(Enum):
    PASSED = "passed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    VIOLATION = "violation"
    ERROR = "error"


@dataclass(frozen=True)
class SandboxSpec:
    """Execution policy for one sandboxed command."""

    workspace_root: str = "."
    cwd: str | None = None
    timeout_seconds: int = 120
    max_output_chars: int = 50_000
    env: Mapping[str, str] = field(default_factory=dict)
    env_allowlist: tuple[str, ...] = DEFAULT_ENV_ALLOWLIST
    enforce_workspace: bool = True
    sandbox_type: str = "local"

    def resolved_cwd(self) -> Path:
        return Path(self.cwd or self.workspace_root).expanduser()


@dataclass(frozen=True)
class SandboxCommandResult:
    """Result returned by a sandbox runner."""

    command: str
    status: SandboxCommandStatus
    sandbox_type: str
    workspace_root: str
    cwd: str
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: float = 0.0
    timeout_seconds: int = 0
    timed_out: bool = False
    violation: str = ""
    error_type: str = ""
    env_keys: list[str] = field(default_factory=list)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == SandboxCommandStatus.PASSED

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "status": self.status.value,
            "sandbox_type": self.sandbox_type,
            "workspace_root": self.workspace_root,
            "cwd": self.cwd,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_ms": self.duration_ms,
            "timeout_seconds": self.timeout_seconds,
            "timed_out": self.timed_out,
            "violation": self.violation,
            "error_type": self.error_type,
            "env_keys": list(self.env_keys),
            "metadata": dict(self.metadata),
        }

    def summary_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "sandbox_type": self.sandbox_type,
            "workspace_root": self.workspace_root,
            "cwd": self.cwd,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "timeout_seconds": self.timeout_seconds,
            "timed_out": self.timed_out,
            "violation": self.violation,
            "error_type": self.error_type,
            "env_keys": list(self.env_keys),
            "metadata": dict(self.metadata),
        }


class SandboxRunner(Protocol):
    def run(self, command: str, *, spec: SandboxSpec) -> SandboxCommandResult: ...


class LocalSandboxRunner:
    """Runs commands locally with workspace, timeout, and environment guards."""

    sandbox_type = "local"

    def run(self, command: str, *, spec: SandboxSpec) -> SandboxCommandResult:
        started = perf_counter()
        workspace_root = Path(spec.workspace_root).expanduser().resolve()
        cwd_result = WorkspacePathPolicy(
            workspace_root,
            enabled=spec.enforce_workspace,
        ).check_path(spec.resolved_cwd(), must_be_dir=True)

        if not cwd_result.allowed or cwd_result.path is None:
            return SandboxCommandResult(
                command=command,
                status=SandboxCommandStatus.VIOLATION,
                sandbox_type=self.sandbox_type,
                workspace_root=str(workspace_root),
                cwd=str(spec.resolved_cwd()),
                duration_ms=_elapsed_ms(started),
                timeout_seconds=spec.timeout_seconds,
                violation=cwd_result.reason or "cwd rejected by workspace policy",
            )

        env = _build_env(spec)
        try:
            completed = subprocess.run(
                command,
                cwd=str(cwd_result.path),
                shell=True,
                capture_output=True,
                text=True,
                timeout=spec.timeout_seconds,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            return SandboxCommandResult(
                command=command,
                status=SandboxCommandStatus.TIMED_OUT,
                sandbox_type=self.sandbox_type,
                workspace_root=str(workspace_root),
                cwd=str(cwd_result.path),
                exit_code=None,
                stdout=_truncate(_coerce_text(exc.stdout), spec.max_output_chars),
                stderr=_truncate(_coerce_text(exc.stderr), spec.max_output_chars),
                duration_ms=_elapsed_ms(started),
                timeout_seconds=spec.timeout_seconds,
                timed_out=True,
                env_keys=sorted(env.keys()),
            )
        except OSError as exc:
            return SandboxCommandResult(
                command=command,
                status=SandboxCommandStatus.ERROR,
                sandbox_type=self.sandbox_type,
                workspace_root=str(workspace_root),
                cwd=str(cwd_result.path),
                stdout="",
                stderr=str(exc),
                duration_ms=_elapsed_ms(started),
                timeout_seconds=spec.timeout_seconds,
                error_type=exc.__class__.__name__,
                env_keys=sorted(env.keys()),
            )

        status = (
            SandboxCommandStatus.PASSED
            if completed.returncode == 0
            else SandboxCommandStatus.FAILED
        )
        return SandboxCommandResult(
            command=command,
            status=status,
            sandbox_type=self.sandbox_type,
            workspace_root=str(workspace_root),
            cwd=str(cwd_result.path),
            exit_code=completed.returncode,
            stdout=_truncate(completed.stdout, spec.max_output_chars),
            stderr=_truncate(completed.stderr, spec.max_output_chars),
            duration_ms=_elapsed_ms(started),
            timeout_seconds=spec.timeout_seconds,
            env_keys=sorted(env.keys()),
        )


class DockerSandboxRunner:
    """Runs commands in a Docker container with a mounted workspace."""

    sandbox_type = "docker"

    def __init__(
        self,
        *,
        docker_binary: str = "docker",
        image: str = "python:3.12-slim",
        network: str = "none",
        memory: str | None = None,
        cpus: str | None = None,
        user: str | None = None,
        mount_mode: str = "rw",
    ) -> None:
        self.docker_binary = docker_binary
        self.image = image
        self.network = network
        self.memory = memory
        self.cpus = cpus
        self.user = user
        self.mount_mode = mount_mode

    def run(self, command: str, *, spec: SandboxSpec) -> SandboxCommandResult:
        started = perf_counter()
        workspace_root = Path(spec.workspace_root).expanduser().resolve()
        cwd_result = WorkspacePathPolicy(
            workspace_root,
            enabled=spec.enforce_workspace,
        ).check_path(spec.resolved_cwd(), must_be_dir=True)

        if not cwd_result.allowed or cwd_result.path is None:
            return SandboxCommandResult(
                command=command,
                status=SandboxCommandStatus.VIOLATION,
                sandbox_type=self.sandbox_type,
                workspace_root=str(workspace_root),
                cwd=str(spec.resolved_cwd()),
                duration_ms=_elapsed_ms(started),
                timeout_seconds=spec.timeout_seconds,
                violation=cwd_result.reason or "cwd rejected by workspace policy",
                metadata=self._metadata(
                    container_name="",
                    container_workdir="",
                    workspace_mount="",
                ),
            )

        container_name = f"codeagentx-{uuid4().hex[:12]}"
        container_workdir = _container_workdir(workspace_root, cwd_result.path)
        workspace_mount = f"{workspace_root}:/workspace:{self.mount_mode}"
        env = _docker_env(spec)
        args = self._docker_run_args(
            command=command,
            container_name=container_name,
            container_workdir=container_workdir,
            workspace_mount=workspace_mount,
            env=env,
        )
        metadata = self._metadata(
            container_name=container_name,
            container_workdir=container_workdir,
            workspace_mount=workspace_mount,
        )

        try:
            completed = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=spec.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            self._cleanup_container(container_name)
            return SandboxCommandResult(
                command=command,
                status=SandboxCommandStatus.TIMED_OUT,
                sandbox_type=self.sandbox_type,
                workspace_root=str(workspace_root),
                cwd=str(cwd_result.path),
                exit_code=None,
                stdout=_truncate(_coerce_text(exc.stdout), spec.max_output_chars),
                stderr=_truncate(_coerce_text(exc.stderr), spec.max_output_chars),
                duration_ms=_elapsed_ms(started),
                timeout_seconds=spec.timeout_seconds,
                timed_out=True,
                env_keys=sorted(env.keys()),
                metadata=metadata,
            )
        except OSError as exc:
            return SandboxCommandResult(
                command=command,
                status=SandboxCommandStatus.ERROR,
                sandbox_type=self.sandbox_type,
                workspace_root=str(workspace_root),
                cwd=str(cwd_result.path),
                stdout="",
                stderr=str(exc),
                duration_ms=_elapsed_ms(started),
                timeout_seconds=spec.timeout_seconds,
                error_type=exc.__class__.__name__,
                env_keys=sorted(env.keys()),
                metadata=metadata,
            )

        status = (
            SandboxCommandStatus.PASSED
            if completed.returncode == 0
            else SandboxCommandStatus.FAILED
        )
        error_type = ""
        if completed.returncode == 125:
            status = SandboxCommandStatus.ERROR
            error_type = "DockerRunError"

        return SandboxCommandResult(
            command=command,
            status=status,
            sandbox_type=self.sandbox_type,
            workspace_root=str(workspace_root),
            cwd=str(cwd_result.path),
            exit_code=completed.returncode,
            stdout=_truncate(completed.stdout, spec.max_output_chars),
            stderr=_truncate(completed.stderr, spec.max_output_chars),
            duration_ms=_elapsed_ms(started),
            timeout_seconds=spec.timeout_seconds,
            error_type=error_type,
            env_keys=sorted(env.keys()),
            metadata=metadata,
        )

    def _docker_run_args(
        self,
        *,
        command: str,
        container_name: str,
        container_workdir: str,
        workspace_mount: str,
        env: Mapping[str, str],
    ) -> list[str]:
        args = [
            self.docker_binary,
            "run",
            "--rm",
            "--name",
            container_name,
            "--network",
            self.network,
            "-v",
            workspace_mount,
            "-w",
            container_workdir,
        ]
        if self.memory:
            args.extend(["--memory", self.memory])
        if self.cpus:
            args.extend(["--cpus", self.cpus])
        if self.user:
            args.extend(["--user", self.user])
        for key, value in sorted(env.items()):
            args.extend(["-e", f"{key}={value}"])
        args.extend([self.image, "/bin/sh", "-lc", command])
        return args

    def _cleanup_container(self, container_name: str) -> None:
        try:
            subprocess.run(
                [self.docker_binary, "rm", "-f", container_name],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except OSError:
            return
        except subprocess.TimeoutExpired:
            return

    def _metadata(
        self,
        *,
        container_name: str,
        container_workdir: str,
        workspace_mount: str,
    ) -> dict[str, Any]:
        return {
            "docker_binary": self.docker_binary,
            "image": self.image,
            "network": self.network,
            "memory": self.memory,
            "cpus": self.cpus,
            "user": self.user,
            "mount_mode": self.mount_mode,
            "container_name": container_name,
            "container_workdir": container_workdir,
            "workspace_mount": workspace_mount,
        }


def create_sandbox_runner(config: Any) -> SandboxRunner:
    sandbox_type = str(getattr(config, "verification_sandbox", "local")).lower()
    if sandbox_type == "local":
        return LocalSandboxRunner()
    if sandbox_type == "docker":
        return DockerSandboxRunner(
            docker_binary=getattr(config, "docker_binary", "docker"),
            image=getattr(config, "docker_sandbox_image", "python:3.12-slim"),
            network=getattr(config, "docker_sandbox_network", "none"),
            memory=getattr(config, "docker_sandbox_memory", None),
            cpus=getattr(config, "docker_sandbox_cpus", None),
            user=getattr(config, "docker_sandbox_user", None),
            mount_mode=getattr(config, "docker_sandbox_mount_mode", "rw"),
        )
    raise ValueError(f"Unsupported verification sandbox: {sandbox_type}")


def _build_env(spec: SandboxSpec) -> dict[str, str]:
    allowed = {key.upper() for key in spec.env_allowlist}
    env = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in allowed
    }
    env.update({str(key): str(value) for key, value in spec.env.items()})
    return env


def _docker_env(spec: SandboxSpec) -> dict[str, str]:
    env = {"PYTHONIOENCODING": "utf-8"}
    env.update({str(key): str(value) for key, value in spec.env.items()})
    return env


def _container_workdir(workspace_root: Path, cwd: Path) -> str:
    relative = cwd.relative_to(workspace_root)
    if str(relative) == ".":
        return "/workspace"
    return "/workspace/" + "/".join(relative.parts)


def _elapsed_ms(started: float) -> float:
    return round((perf_counter() - started) * 1000, 3)


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return text[:max_chars] + f"\n... truncated {omitted} chars"


def _coerce_text(text: str | bytes | None) -> str:
    if text is None:
        return ""
    if isinstance(text, bytes):
        return text.decode(errors="replace")
    return text
