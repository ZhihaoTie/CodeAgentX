"""Outcome verification for completed agent runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from codeagentx.agent.state import AgentState, utc_now_iso
from codeagentx.sandbox import LocalSandboxRunner, SandboxCommandStatus, SandboxRunner, SandboxSpec
from codeagentx.sandbox import create_sandbox_runner
from codeagentx.sandbox import write_sandbox_artifacts

from .constraints import TaskConstraintEvaluation, TaskConstraintVerifier
from .test_parser import parse_test_output


class VerificationStatus(Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class VerificationCheck:
    name: str
    status: VerificationStatus
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class VerificationReport:
    status: VerificationStatus
    summary: str
    checks: list[VerificationCheck] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)

    @property
    def passed(self) -> bool:
        return self.status == VerificationStatus.PASSED

    @property
    def failed(self) -> bool:
        return self.status == VerificationStatus.FAILED

    @property
    def skipped(self) -> bool:
        return self.status == VerificationStatus.SKIPPED

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "summary": self.summary,
            "checks": [check.to_dict() for check in self.checks],
            "created_at": self.created_at,
        }


class OutcomeVerifier:
    """Runs explicit acceptance checks after the model stops using tools."""

    def __init__(
        self,
        command: str | None = None,
        *,
        cwd: str | Path | None = None,
        timeout_seconds: int = 120,
        max_output_chars: int = 50_000,
        sandbox_runner: SandboxRunner | None = None,
        sandbox_type: str = "local",
        task_constraint_verifier: TaskConstraintVerifier | None = None,
        enable_sandbox_artifacts: bool = True,
        sandbox_artifact_dir: str | Path | None = None,
        sandbox_artifact_task_id: str | None = None,
        sandbox_snapshot_max_files: int = 2_000,
        sandbox_snapshot_max_recorded_files: int = 100,
    ) -> None:
        self.command = command
        self.cwd = Path(cwd) if cwd is not None else Path.cwd()
        self.timeout_seconds = timeout_seconds
        self.max_output_chars = max_output_chars
        self.sandbox_runner = sandbox_runner or LocalSandboxRunner()
        self.sandbox_type = sandbox_type
        self.task_constraint_verifier = task_constraint_verifier or TaskConstraintVerifier(
            workspace_root=self.cwd,
        )
        self.enable_sandbox_artifacts = enable_sandbox_artifacts
        self.sandbox_artifact_dir = (
            Path(sandbox_artifact_dir)
            if sandbox_artifact_dir is not None
            else None
        )
        self.sandbox_artifact_task_id = sandbox_artifact_task_id
        self.sandbox_snapshot_max_files = sandbox_snapshot_max_files
        self.sandbox_snapshot_max_recorded_files = sandbox_snapshot_max_recorded_files

    @classmethod
    def from_config(cls, config: Any) -> "OutcomeVerifier":
        return cls(
            command=getattr(config, "verification_command", None),
            cwd=getattr(config, "workspace_root", "."),
            timeout_seconds=getattr(config, "verification_timeout_seconds", 120),
            max_output_chars=getattr(config, "max_output_chars", 50_000),
            sandbox_runner=create_sandbox_runner(config),
            sandbox_type=getattr(config, "verification_sandbox", "local"),
            enable_sandbox_artifacts=getattr(config, "enable_sandbox_artifacts", True),
            sandbox_artifact_dir=getattr(config, "sandbox_artifact_dir", None),
            sandbox_artifact_task_id=getattr(config, "sandbox_artifact_task_id", None),
            sandbox_snapshot_max_files=getattr(config, "sandbox_snapshot_max_files", 2_000),
            sandbox_snapshot_max_recorded_files=getattr(
                config,
                "sandbox_snapshot_max_recorded_files",
                100,
            ),
            task_constraint_verifier=(
                TaskConstraintVerifier.from_config(config)
                if getattr(config, "enable_task_constraints", True)
                else TaskConstraintVerifier(workspace_root=getattr(config, "workspace_root", "."))
            ),
        )

    def verify(self, state: AgentState, final_text: str) -> VerificationReport:
        checks = [
            self._check_final_response(final_text),
            self._check_tool_error_summary(state),
        ]
        task_constraint_check = self._check_task_constraints(state, final_text)
        if task_constraint_check is not None:
            checks.append(task_constraint_check)

        if not self.command:
            checks.append(VerificationCheck(
                name="verification_command",
                status=VerificationStatus.SKIPPED,
                message="No verification command configured.",
            ))
            failed = [check for check in checks if check.status == VerificationStatus.FAILED]
            if failed:
                return VerificationReport(
                    status=VerificationStatus.FAILED,
                    summary="Verification failed: " + "; ".join(check.message for check in failed),
                    checks=checks,
                )
            if _has_passing_deterministic_constraints(checks):
                return VerificationReport(
                    status=VerificationStatus.PASSED,
                    summary="All deterministic task constraints passed.",
                    checks=checks,
                )
            return VerificationReport(
                status=VerificationStatus.SKIPPED,
                summary="Model stopped without an explicit verifier.",
                checks=checks,
            )

        checks.append(self._run_command_check(state))
        failed = [check for check in checks if check.status == VerificationStatus.FAILED]
        if failed:
            return VerificationReport(
                status=VerificationStatus.FAILED,
                summary="Verification failed: " + "; ".join(check.message for check in failed),
                checks=checks,
            )

        return VerificationReport(
            status=VerificationStatus.PASSED,
            summary="All configured verification checks passed.",
            checks=checks,
        )

    def _check_task_constraints(
        self,
        state: AgentState,
        final_text: str,
    ) -> VerificationCheck | None:
        if not self.task_constraint_verifier.configured:
            return None

        result = self.task_constraint_verifier.verify(state, final_text)
        return _task_constraint_check(result)

    def _check_final_response(self, final_text: str) -> VerificationCheck:
        if final_text.strip():
            return VerificationCheck(
                name="final_response",
                status=VerificationStatus.PASSED,
                message="Model returned a final response.",
            )
        return VerificationCheck(
            name="final_response",
            status=VerificationStatus.FAILED,
            message="Model stopped without final text.",
        )

    def _check_tool_error_summary(self, state: AgentState) -> VerificationCheck:
        failed_tool_calls = state.error_count()
        if failed_tool_calls == 0:
            return VerificationCheck(
                name="tool_errors",
                status=VerificationStatus.PASSED,
                message="No failed tool calls were recorded.",
                metadata={"failed_tool_calls": 0},
            )
        return VerificationCheck(
            name="tool_errors",
            status=VerificationStatus.PASSED,
            message=f"{failed_tool_calls} failed tool call(s) were recorded before completion.",
            metadata={"failed_tool_calls": failed_tool_calls},
        )

    def _run_command_check(self, state: AgentState) -> VerificationCheck:
        result = self.sandbox_runner.run(
            self.command,
            spec=SandboxSpec(
                workspace_root=str(self.cwd),
                cwd=str(self.cwd),
                timeout_seconds=self.timeout_seconds,
                max_output_chars=self.max_output_chars,
                sandbox_type=self.sandbox_type,
            ),
        )
        artifacts = self._write_artifacts(result, state)

        status = VerificationStatus.PASSED
        message = "Verification command exited with code 0."
        if result.status == SandboxCommandStatus.TIMED_OUT:
            status = VerificationStatus.FAILED
            message = f"Verification command timed out after {self.timeout_seconds}s."
        elif result.status == SandboxCommandStatus.VIOLATION:
            status = VerificationStatus.FAILED
            message = f"Verification command violated sandbox policy: {result.violation}"
        elif result.status == SandboxCommandStatus.ERROR:
            status = VerificationStatus.FAILED
            message = f"Verification command failed in sandbox: {result.error_type}."
        elif result.exit_code != 0:
            status = VerificationStatus.FAILED
            message = f"Verification command exited with code {result.exit_code}."

        test_result = parse_test_output(result.stdout, result.stderr)
        return VerificationCheck(
            name="verification_command",
            status=status,
            message=message,
            metadata={
                "command": self.command,
                "cwd": result.cwd,
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "timeout_seconds": self.timeout_seconds,
                "sandbox": result.summary_dict(),
                "artifacts": artifacts,
                "test_result": test_result.to_dict(),
            },
        )

    def _write_artifacts(
        self,
        result: Any,
        state: AgentState,
    ) -> dict[str, Any]:
        if not self.enable_sandbox_artifacts or self.sandbox_artifact_dir is None:
            return {}
        return write_sandbox_artifacts(
            result,
            self.sandbox_artifact_dir,
            kind="verification",
            task_id=self.sandbox_artifact_task_id or state.task_id,
            snapshot_max_files=self.sandbox_snapshot_max_files,
            snapshot_max_recorded_files=self.sandbox_snapshot_max_recorded_files,
        )


def _task_constraint_check(result: TaskConstraintEvaluation) -> VerificationCheck:
    return VerificationCheck(
        name="task_constraints",
        status=VerificationStatus(result.status),
        message=result.message,
        metadata=dict(result.metadata),
    )


def _has_passing_deterministic_constraints(checks: list[VerificationCheck]) -> bool:
    for check in checks:
        if check.name != "task_constraints" or check.status != VerificationStatus.PASSED:
            continue
        if check.metadata.get("deterministic") is True:
            return True
    return False
