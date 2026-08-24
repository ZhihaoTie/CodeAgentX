"""Benchmark harness for repeatable CodeAgent-X task runs."""

from __future__ import annotations

import json
import shutil
import time
from fnmatch import fnmatch
from collections.abc import Callable, Iterable, Mapping
from contextlib import redirect_stdout
from dataclasses import dataclass, field, fields, replace
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any
from uuid import uuid4

from codeagentx.agent import AgentLoop
from codeagentx.config import Config, PermissionMode
from codeagentx.models import ModelProvider
from codeagentx.sandbox import SandboxSpec, create_sandbox_runner
from codeagentx.sandbox import write_sandbox_artifacts
from codeagentx.tools.base import ToolRegistry

from .git_diff import GitDiffReport, collect_git_diff, write_git_diff_artifacts
from .metrics import analyze_state


BENCHMARK_SCHEMA_VERSION = "codeagentx.benchmark.v1"
BENCHMARK_ABLATION_SCHEMA_VERSION = "codeagentx.benchmark_ablation.v1"
MAX_RECORDED_OUTPUT_CHARS = 12_000
ProviderFactory = Callable[["BenchmarkTaskSpec"], ModelProvider]
BENCHMARK_MEMORY_POLICIES = {"shared", "isolated", "disabled"}
ABLATION_AVERAGE_METRICS = (
    "turns",
    "tool_calls",
    "failed_tool_calls",
    "tool_error_rate",
    "test_runs",
    "edit_count",
    "read_count",
    "plan_progress",
    "plan_completed_steps",
    "plan_blocked_steps",
    "plan_repair_count",
    "patch_policy_violation_count",
    "patch_policy_changed_files",
    "patch_policy_changed_lines",
    "git_diff_patch_bytes",
    "git_diff_changed_files",
    "git_diff_forbidden_path_count",
    "context_ranking_count",
    "context_candidate_count",
    "reflection_signal_count",
    "reflection_retry_count",
    "tool_planning_guidance_count",
    "tool_planning_guidance_blocked",
    "tool_planning_guidance_warnings",
    "memory_retrieval_count",
    "memory_hit_count",
    "memory_candidate_count",
    "memory_filtered_count",
    "memory_prompt_injected_count",
    "memory_extraction_count",
    "memory_stored_count",
    "memory_duplicate_count",
    "budget_turns",
    "budget_tool_calls",
    "budget_input_tokens",
    "budget_output_tokens",
    "budget_total_tokens",
    "budget_elapsed_seconds",
    "budget_exhausted",
)


@dataclass(frozen=True)
class BenchmarkTaskSpec:
    """A reproducible software-engineering task definition."""

    task_id: str
    goal: str
    workspace_root: str = "."
    verification_command: str | None = None
    setup_command: str | None = None
    repository_commit: str | None = None
    success_criteria: list[str] = field(default_factory=list)
    enable_task_constraints: bool | None = None
    required_changed_paths: list[str] = field(default_factory=list)
    forbidden_changed_paths: list[str] = field(default_factory=list)
    required_final_response_substrings: list[str] = field(default_factory=list)
    forbidden_final_response_substrings: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    max_turns: int | None = None
    max_tool_calls: int | None = None
    max_run_seconds: float | None = None
    permission_mode: PermissionMode | None = None
    verification_timeout_seconds: int | None = None
    verification_sandbox: str | None = None
    enable_sandbox_artifacts: bool | None = None
    sandbox_snapshot_max_files: int | None = None
    sandbox_snapshot_max_recorded_files: int | None = None
    docker_sandbox_image: str | None = None
    docker_sandbox_network: str | None = None
    docker_sandbox_memory: str | None = None
    docker_sandbox_cpus: str | None = None
    setup_timeout_seconds: int = 120
    enable_runtime_planning: bool | None = None
    enable_context_ranking: bool | None = None
    context_ranking_limit: int | None = None
    enable_long_term_memory: bool | None = None
    memory_store_path: str | None = None
    memory_retrieval_limit: int | None = None
    memory_min_score: int | None = None
    memory_prompt_max_chars: int | None = None
    auto_rollback_on_verification_failure: bool | None = None
    enable_patch_policy: bool | None = None
    patch_policy_max_changed_files: int | None = None
    patch_policy_max_total_changed_lines: int | None = None
    enable_failure_reflection: bool | None = None
    max_reflection_retries: int | None = None
    enable_retry_strategy_matrix: bool | None = None
    enable_tool_planning_guidance: bool | None = None
    enable_git_diff_artifact: bool | None = None
    git_diff_base_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
        *,
        defaults: Mapping[str, Any] | None = None,
        base_dir: str | Path | None = None,
    ) -> "BenchmarkTaskSpec":
        merged: dict[str, Any] = dict(defaults or {})
        merged.update(dict(payload))

        task_id = merged.get("task_id", merged.get("id"))
        goal = merged.get("goal")
        if not task_id:
            raise ValueError("benchmark task is missing 'id' or 'task_id'")
        if not goal:
            raise ValueError(f"benchmark task {task_id!r} is missing 'goal'")

        workspace_root = str(merged.get("workspace_root", "."))
        if base_dir is not None:
            workspace_root = _resolve_maybe_relative(workspace_root, Path(base_dir))

        return cls(
            task_id=str(task_id),
            goal=str(goal),
            workspace_root=workspace_root,
            verification_command=_optional_str(merged.get("verification_command")),
            setup_command=_optional_str(merged.get("setup_command")),
            repository_commit=_optional_str(merged.get("repository_commit")),
            success_criteria=_string_list(merged.get("success_criteria")),
            enable_task_constraints=_optional_bool(merged.get("enable_task_constraints")),
            required_changed_paths=_string_list(merged.get("required_changed_paths")),
            forbidden_changed_paths=_string_list(merged.get("forbidden_changed_paths")),
            required_final_response_substrings=_string_list(
                merged.get("required_final_response_substrings")
            ),
            forbidden_final_response_substrings=_string_list(
                merged.get("forbidden_final_response_substrings")
            ),
            tags=_string_list(merged.get("tags")),
            max_turns=_optional_int(merged.get("max_turns")),
            max_tool_calls=_optional_int(merged.get("max_tool_calls")),
            max_run_seconds=_optional_float(merged.get("max_run_seconds")),
            permission_mode=_coerce_permission_mode(merged.get("permission_mode", merged.get("mode"))),
            verification_timeout_seconds=_optional_int(merged.get("verification_timeout_seconds")),
            verification_sandbox=_optional_str(merged.get("verification_sandbox")),
            enable_sandbox_artifacts=_optional_bool(merged.get("enable_sandbox_artifacts")),
            sandbox_snapshot_max_files=_optional_int(merged.get("sandbox_snapshot_max_files")),
            sandbox_snapshot_max_recorded_files=_optional_int(
                merged.get("sandbox_snapshot_max_recorded_files")
            ),
            docker_sandbox_image=_optional_str(merged.get("docker_sandbox_image")),
            docker_sandbox_network=_optional_str(merged.get("docker_sandbox_network")),
            docker_sandbox_memory=_optional_str(merged.get("docker_sandbox_memory")),
            docker_sandbox_cpus=_optional_str(merged.get("docker_sandbox_cpus")),
            setup_timeout_seconds=int(merged.get("setup_timeout_seconds", 120)),
            enable_runtime_planning=_optional_bool(merged.get("enable_runtime_planning")),
            enable_context_ranking=_optional_bool(merged.get("enable_context_ranking")),
            context_ranking_limit=_optional_int(merged.get("context_ranking_limit")),
            enable_long_term_memory=_optional_bool(merged.get("enable_long_term_memory")),
            memory_store_path=_optional_str(merged.get("memory_store_path")),
            memory_retrieval_limit=_optional_int(merged.get("memory_retrieval_limit")),
            memory_min_score=_optional_int(merged.get("memory_min_score")),
            memory_prompt_max_chars=_optional_int(merged.get("memory_prompt_max_chars")),
            auto_rollback_on_verification_failure=_optional_bool(
                merged.get("auto_rollback_on_verification_failure")
            ),
            enable_patch_policy=_optional_bool(merged.get("enable_patch_policy")),
            patch_policy_max_changed_files=_optional_int(
                merged.get("patch_policy_max_changed_files")
            ),
            patch_policy_max_total_changed_lines=_optional_int(
                merged.get("patch_policy_max_total_changed_lines")
            ),
            enable_failure_reflection=_optional_bool(merged.get("enable_failure_reflection")),
            max_reflection_retries=_optional_int(merged.get("max_reflection_retries")),
            enable_retry_strategy_matrix=_optional_bool(
                merged.get("enable_retry_strategy_matrix")
            ),
            enable_tool_planning_guidance=_optional_bool(
                merged.get("enable_tool_planning_guidance")
            ),
            enable_git_diff_artifact=_optional_bool(merged.get("enable_git_diff_artifact")),
            git_diff_base_ref=_optional_str(merged.get("git_diff_base_ref")),
            metadata=dict(merged.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "goal": self.goal,
            "workspace_root": self.workspace_root,
            "verification_command": self.verification_command,
            "setup_command": self.setup_command,
            "repository_commit": self.repository_commit,
            "success_criteria": list(self.success_criteria),
            "enable_task_constraints": self.enable_task_constraints,
            "required_changed_paths": list(self.required_changed_paths),
            "forbidden_changed_paths": list(self.forbidden_changed_paths),
            "required_final_response_substrings": list(self.required_final_response_substrings),
            "forbidden_final_response_substrings": list(self.forbidden_final_response_substrings),
            "tags": list(self.tags),
            "max_turns": self.max_turns,
            "max_tool_calls": self.max_tool_calls,
            "max_run_seconds": self.max_run_seconds,
            "permission_mode": self.permission_mode.value if self.permission_mode else None,
            "verification_timeout_seconds": self.verification_timeout_seconds,
            "verification_sandbox": self.verification_sandbox,
            "enable_sandbox_artifacts": self.enable_sandbox_artifacts,
            "sandbox_snapshot_max_files": self.sandbox_snapshot_max_files,
            "sandbox_snapshot_max_recorded_files": self.sandbox_snapshot_max_recorded_files,
            "docker_sandbox_image": self.docker_sandbox_image,
            "docker_sandbox_network": self.docker_sandbox_network,
            "docker_sandbox_memory": self.docker_sandbox_memory,
            "docker_sandbox_cpus": self.docker_sandbox_cpus,
            "setup_timeout_seconds": self.setup_timeout_seconds,
            "enable_runtime_planning": self.enable_runtime_planning,
            "enable_context_ranking": self.enable_context_ranking,
            "context_ranking_limit": self.context_ranking_limit,
            "enable_long_term_memory": self.enable_long_term_memory,
            "memory_store_path": self.memory_store_path,
            "memory_retrieval_limit": self.memory_retrieval_limit,
            "memory_min_score": self.memory_min_score,
            "memory_prompt_max_chars": self.memory_prompt_max_chars,
            "auto_rollback_on_verification_failure": self.auto_rollback_on_verification_failure,
            "enable_patch_policy": self.enable_patch_policy,
            "patch_policy_max_changed_files": self.patch_policy_max_changed_files,
            "patch_policy_max_total_changed_lines": self.patch_policy_max_total_changed_lines,
            "enable_failure_reflection": self.enable_failure_reflection,
            "max_reflection_retries": self.max_reflection_retries,
            "enable_retry_strategy_matrix": self.enable_retry_strategy_matrix,
            "enable_tool_planning_guidance": self.enable_tool_planning_guidance,
            "enable_git_diff_artifact": self.enable_git_diff_artifact,
            "git_diff_base_ref": self.git_diff_base_ref,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class BenchmarkCommandResult:
    command: str
    exit_code: int | None
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
    timed_out: bool = False
    sandbox: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_seconds": self.duration_seconds,
            "timed_out": self.timed_out,
            "passed": self.passed,
            "sandbox": dict(self.sandbox),
            "artifacts": dict(self.artifacts),
        }


@dataclass(frozen=True)
class BenchmarkTaskResult:
    task_id: str
    goal: str
    status: str
    resolved: bool
    duration_seconds: float
    verification_status: str | None = None
    original_workspace_root: str | None = None
    run_workspace_root: str | None = None
    trajectory_task_id: str | None = None
    state_path: str | None = None
    events_path: str | None = None
    final_text: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    setup_result: BenchmarkCommandResult | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "goal": self.goal,
            "status": self.status,
            "resolved": self.resolved,
            "duration_seconds": self.duration_seconds,
            "verification_status": self.verification_status,
            "original_workspace_root": self.original_workspace_root,
            "run_workspace_root": self.run_workspace_root,
            "trajectory_task_id": self.trajectory_task_id,
            "state_path": self.state_path,
            "events_path": self.events_path,
            "final_text": self.final_text,
            "metrics": dict(self.metrics),
            "artifacts": [dict(item) for item in self.artifacts],
            "setup_result": (
                self.setup_result.to_dict()
                if self.setup_result is not None
                else None
            ),
            "error": self.error,
        }


@dataclass(frozen=True)
class BenchmarkReport:
    run_id: str
    created_at: str
    output_dir: str
    tasks: list[BenchmarkTaskSpec]
    results: list[BenchmarkTaskResult]
    memory_policy: Mapping[str, Any] = field(default_factory=dict)

    @property
    def total_tasks(self) -> int:
        return len(self.results)

    @property
    def resolved_tasks(self) -> int:
        return sum(1 for result in self.results if result.resolved)

    @property
    def failed_tasks(self) -> int:
        return self.total_tasks - self.resolved_tasks

    @property
    def resolved_rate(self) -> float:
        if self.total_tasks == 0:
            return 0.0
        return self.resolved_tasks / self.total_tasks

    @property
    def report_path(self) -> str:
        return str(Path(self.output_dir) / "report.json")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": BENCHMARK_SCHEMA_VERSION,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "output_dir": self.output_dir,
            "memory_policy": dict(self.memory_policy),
            "summary": self.summary(),
            "tasks": [task.to_dict() for task in self.tasks],
            "results": [result.to_dict() for result in self.results],
        }

    def summary(self) -> dict[str, Any]:
        return _report_summary(self)

    def save(self) -> Path:
        output_dir = Path(self.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "report.json"
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def _average_metric(self, key: str) -> float:
        values = [
            result.metrics[key]
            for result in self.results
            if isinstance(result.metrics.get(key), (int, float))
        ]
        if not values:
            return 0.0
        return sum(values) / len(values)


@dataclass(frozen=True)
class BenchmarkAblationVariant:
    """A named benchmark configuration override for module ablation."""

    name: str
    description: str = ""
    overrides: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | str) -> "BenchmarkAblationVariant":
        if isinstance(payload, str):
            return cls(name=payload)
        if not isinstance(payload, Mapping):
            raise ValueError("ablation variant must be a string or object")

        name = payload.get("name", payload.get("id"))
        if not name:
            raise ValueError("ablation variant is missing 'name' or 'id'")

        overrides = payload.get("overrides", payload.get("config", {}))
        if not isinstance(overrides, Mapping):
            raise ValueError(f"ablation variant {name!r} overrides must be an object")

        return cls(
            name=str(name),
            description=str(payload.get("description", "") or ""),
            overrides=dict(overrides),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "overrides": dict(self.overrides),
        }


@dataclass(frozen=True)
class BenchmarkAblationVariantResult:
    variant: BenchmarkAblationVariant
    report: BenchmarkReport

    @property
    def summary(self) -> dict[str, Any]:
        return _variant_summary(self.report)

    def to_dict(self, *, baseline_summary: Mapping[str, Any] | None = None) -> dict[str, Any]:
        payload = {
            "variant": self.variant.to_dict(),
            "report_path": self.report.report_path,
            "memory_policy": dict(self.report.memory_policy),
            "summary": self.summary,
        }
        if baseline_summary is not None:
            payload["delta_vs_baseline"] = _delta_vs_baseline(
                baseline_summary,
                self.summary,
            )
        return payload


@dataclass(frozen=True)
class BenchmarkAblationReport:
    run_id: str
    created_at: str
    output_dir: str
    tasks: list[BenchmarkTaskSpec]
    variant_results: list[BenchmarkAblationVariantResult]

    @property
    def report_path(self) -> str:
        return str(Path(self.output_dir) / "ablation_report.json")

    @property
    def total_task_runs(self) -> int:
        return sum(result.report.total_tasks for result in self.variant_results)

    @property
    def baseline_variant(self) -> str | None:
        if not self.variant_results:
            return None
        return self.variant_results[0].variant.name

    def to_dict(self) -> dict[str, Any]:
        baseline_summary = (
            self.variant_results[0].summary
            if self.variant_results
            else None
        )
        return {
            "schema_version": BENCHMARK_ABLATION_SCHEMA_VERSION,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "output_dir": self.output_dir,
            "summary": {
                "variant_count": len(self.variant_results),
                "task_count": len(self.tasks),
                "total_task_runs": self.total_task_runs,
                "baseline_variant": self.baseline_variant,
                "best_resolved_rate_variant": _best_variant_name(self.variant_results),
            },
            "tasks": [task.to_dict() for task in self.tasks],
            "variants": [result.variant.to_dict() for result in self.variant_results],
            "variant_results": [
                result.to_dict(baseline_summary=baseline_summary)
                for result in self.variant_results
            ],
            "task_outcomes": _task_outcome_matrix(self.variant_results, self.tasks),
        }

    def save(self) -> Path:
        output_dir = Path(self.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "ablation_report.json"
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path


class BenchmarkRunner:
    """Runs fixed task specs and writes a benchmark report artifact."""

    def __init__(
        self,
        *,
        base_config: Config | None = None,
        registry: ToolRegistry | None = None,
        provider_factory: ProviderFactory | None = None,
        output_dir: str | Path = ".codeagentx/benchmarks",
        final_config_overrides: Mapping[str, Any] | None = None,
        memory_policy: str = "shared",
    ) -> None:
        self.base_config = (
            base_config if base_config is not None else Config.from_env()
        )
        self.registry = registry
        self.provider_factory = provider_factory
        self.output_dir = Path(output_dir)
        self.final_config_overrides = dict(final_config_overrides or {})
        self.memory_policy = _normalize_benchmark_memory_policy(memory_policy)

    def run(
        self,
        tasks: Iterable[BenchmarkTaskSpec],
        *,
        run_id: str | None = None,
    ) -> BenchmarkReport:
        task_list = list(tasks)
        if not task_list:
            raise ValueError("benchmark requires at least one task")

        run_id = run_id or _new_run_id()
        run_dir = self.output_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "tasks.json").write_text(
            json.dumps([task.to_dict() for task in task_list], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        results = [
            self._run_one(task, run_dir=run_dir)
            for task in task_list
        ]
        report = BenchmarkReport(
            run_id=run_id,
            created_at=_utc_now_iso(),
            output_dir=str(run_dir),
            tasks=task_list,
            results=results,
            memory_policy=_benchmark_memory_policy_payload(
                self.memory_policy,
                results=results,
            ),
        )
        report.save()
        return report

    def _run_one(self, task: BenchmarkTaskSpec, *, run_dir: Path) -> BenchmarkTaskResult:
        started = time.perf_counter()
        original_workspace = Path(
            task.workspace_root or self.base_config.workspace_root
        ).resolve()
        run_workspace = _prepare_task_workspace(
            original_workspace,
            run_dir=run_dir,
            task_id=task.task_id,
            preserve_git_metadata=bool(task.enable_git_diff_artifact),
        )
        config = self._config_for_task(
            task,
            run_dir=run_dir,
            workspace_root=run_workspace,
        )
        setup_result = None

        if task.setup_command:
            setup_result = _run_command(
                task.setup_command,
                cwd=config.workspace_root,
                timeout_seconds=task.setup_timeout_seconds,
                config=config,
                artifact_kind="setup",
                task_id=task.task_id,
            )
            if not setup_result.passed:
                git_diff_artifact, git_diff_metrics = _collect_task_git_diff_artifact(
                    task,
                    run_workspace=run_workspace,
                    run_dir=run_dir,
                    base_artifact_dir=self.base_config.sandbox_artifact_dir,
                )
                return BenchmarkTaskResult(
                    task_id=task.task_id,
                    goal=task.goal,
                    status="setup_failed",
                    resolved=False,
                    duration_seconds=_elapsed(started),
                    original_workspace_root=str(original_workspace),
                    run_workspace_root=str(run_workspace),
                    metrics=git_diff_metrics,
                    artifacts=_artifact_index(
                        setup_result=setup_result,
                        state=None,
                        git_diff_artifact=git_diff_artifact,
                    ),
                    setup_result=setup_result,
                    error="setup command failed",
                )

        agent: AgentLoop | None = None
        try:
            provider = self.provider_factory(task) if self.provider_factory else None
            agent = AgentLoop(
                config=config,
                registry=self.registry or ToolRegistry.default(),
                provider=provider,
            )
            with redirect_stdout(StringIO()):
                final_text = agent.run(task.goal)
        except Exception as exc:
            state = agent.last_state if agent is not None else None
            metrics = analyze_state(state).to_dict() if state is not None else {}
            git_diff_artifact, git_diff_metrics = _collect_task_git_diff_artifact(
                task,
                run_workspace=run_workspace,
                run_dir=run_dir,
                base_artifact_dir=self.base_config.sandbox_artifact_dir,
            )
            metrics.update(git_diff_metrics)
            return BenchmarkTaskResult(
                task_id=task.task_id,
                goal=task.goal,
                status="errored",
                resolved=False,
                duration_seconds=_elapsed(started),
                verification_status=_verification_status(metrics),
                original_workspace_root=str(original_workspace),
                run_workspace_root=str(run_workspace),
                trajectory_task_id=state.task_id if state is not None else None,
                state_path=_state_path(agent, state),
                events_path=_events_path(agent, state),
                metrics=metrics,
                artifacts=_artifact_index(
                    setup_result=setup_result,
                    state=state,
                    git_diff_artifact=git_diff_artifact,
                ),
                setup_result=setup_result,
                error=f"{exc.__class__.__name__}: {exc}",
            )

        state = agent.last_state
        metrics = analyze_state(state).to_dict() if state is not None else {}
        git_diff_artifact, git_diff_metrics = _collect_task_git_diff_artifact(
            task,
            run_workspace=run_workspace,
            run_dir=run_dir,
            base_artifact_dir=self.base_config.sandbox_artifact_dir,
        )
        metrics.update(git_diff_metrics)
        git_diff_policy_failed = _git_diff_policy_failed(metrics)
        return BenchmarkTaskResult(
            task_id=task.task_id,
            goal=task.goal,
            status=(
                "failed"
                if git_diff_policy_failed
                else str(metrics.get("status", "unknown"))
            ),
            resolved=bool(
                metrics.get("success", False)
                and metrics.get("verified_success", False)
                and not git_diff_policy_failed
            ),
            duration_seconds=_elapsed(started),
            verification_status=_verification_status(metrics),
            original_workspace_root=str(original_workspace),
            run_workspace_root=str(run_workspace),
            trajectory_task_id=state.task_id if state is not None else None,
            state_path=_state_path(agent, state),
            events_path=_events_path(agent, state),
            final_text=_truncate(final_text),
            metrics=metrics,
            artifacts=_artifact_index(
                setup_result=setup_result,
                state=state,
                git_diff_artifact=git_diff_artifact,
            ),
            setup_result=setup_result,
        )

    def _config_for_task(
        self,
        task: BenchmarkTaskSpec,
        *,
        run_dir: Path,
        workspace_root: Path,
    ) -> Config:
        trajectory_dir = run_dir / "trajectories" / task.task_id
        enable_sandbox_artifacts = (
            task.enable_sandbox_artifacts
            if task.enable_sandbox_artifacts is not None
            else self.base_config.enable_sandbox_artifacts
        )
        enable_long_term_memory = (
            task.enable_long_term_memory
            if task.enable_long_term_memory is not None
            else self.base_config.enable_long_term_memory
        )
        artifact_root = _benchmark_artifact_root(
            self.base_config.sandbox_artifact_dir,
            run_dir=run_dir,
        )
        config = replace(
            self.base_config,
            workspace_root=str(workspace_root),
            trajectory_dir=str(trajectory_dir),
            sandbox_artifact_dir=(
                str(artifact_root)
                if enable_sandbox_artifacts
                else None
            ),
            sandbox_artifact_task_id=task.task_id,
            verification_command=(
                task.verification_command
                if task.verification_command is not None
                else self.base_config.verification_command
            ),
            enable_task_constraints=(
                task.enable_task_constraints
                if task.enable_task_constraints is not None
                else self.base_config.enable_task_constraints
            ),
            task_success_criteria=(
                task.success_criteria
                if task.success_criteria
                else self.base_config.task_success_criteria
            ),
            task_required_changed_paths=(
                task.required_changed_paths
                if task.required_changed_paths
                else self.base_config.task_required_changed_paths
            ),
            task_forbidden_changed_paths=(
                task.forbidden_changed_paths
                if task.forbidden_changed_paths
                else self.base_config.task_forbidden_changed_paths
            ),
            task_required_final_response_substrings=(
                task.required_final_response_substrings
                if task.required_final_response_substrings
                else self.base_config.task_required_final_response_substrings
            ),
            task_forbidden_final_response_substrings=(
                task.forbidden_final_response_substrings
                if task.forbidden_final_response_substrings
                else self.base_config.task_forbidden_final_response_substrings
            ),
            verification_timeout_seconds=(
                task.verification_timeout_seconds
                if task.verification_timeout_seconds is not None
                else self.base_config.verification_timeout_seconds
            ),
            verification_sandbox=(
                task.verification_sandbox
                if task.verification_sandbox is not None
                else self.base_config.verification_sandbox
            ),
            enable_sandbox_artifacts=(
                enable_sandbox_artifacts
            ),
            sandbox_snapshot_max_files=(
                task.sandbox_snapshot_max_files
                if task.sandbox_snapshot_max_files is not None
                else self.base_config.sandbox_snapshot_max_files
            ),
            sandbox_snapshot_max_recorded_files=(
                task.sandbox_snapshot_max_recorded_files
                if task.sandbox_snapshot_max_recorded_files is not None
                else self.base_config.sandbox_snapshot_max_recorded_files
            ),
            docker_sandbox_image=(
                task.docker_sandbox_image
                if task.docker_sandbox_image is not None
                else self.base_config.docker_sandbox_image
            ),
            docker_sandbox_network=(
                task.docker_sandbox_network
                if task.docker_sandbox_network is not None
                else self.base_config.docker_sandbox_network
            ),
            docker_sandbox_memory=(
                task.docker_sandbox_memory
                if task.docker_sandbox_memory is not None
                else self.base_config.docker_sandbox_memory
            ),
            docker_sandbox_cpus=(
                task.docker_sandbox_cpus
                if task.docker_sandbox_cpus is not None
                else self.base_config.docker_sandbox_cpus
            ),
            max_turns=task.max_turns if task.max_turns is not None else self.base_config.max_turns,
            max_tool_calls=(
                task.max_tool_calls
                if task.max_tool_calls is not None
                else self.base_config.max_tool_calls
            ),
            max_run_seconds=(
                task.max_run_seconds
                if task.max_run_seconds is not None
                else self.base_config.max_run_seconds
            ),
            permission_mode=task.permission_mode or self.base_config.permission_mode,
            enable_runtime_planning=(
                task.enable_runtime_planning
                if task.enable_runtime_planning is not None
                else self.base_config.enable_runtime_planning
            ),
            enable_context_ranking=(
                task.enable_context_ranking
                if task.enable_context_ranking is not None
                else self.base_config.enable_context_ranking
            ),
            context_ranking_limit=(
                task.context_ranking_limit
                if task.context_ranking_limit is not None
                else self.base_config.context_ranking_limit
            ),
            enable_long_term_memory=enable_long_term_memory,
            memory_store_path=(
                task.memory_store_path
                if task.memory_store_path is not None
                else self.base_config.memory_store_path
            ),
            memory_retrieval_limit=(
                task.memory_retrieval_limit
                if task.memory_retrieval_limit is not None
                else self.base_config.memory_retrieval_limit
            ),
            memory_min_score=(
                task.memory_min_score
                if task.memory_min_score is not None
                else self.base_config.memory_min_score
            ),
            memory_prompt_max_chars=(
                task.memory_prompt_max_chars
                if task.memory_prompt_max_chars is not None
                else self.base_config.memory_prompt_max_chars
            ),
            auto_rollback_on_verification_failure=(
                task.auto_rollback_on_verification_failure
                if task.auto_rollback_on_verification_failure is not None
                else self.base_config.auto_rollback_on_verification_failure
            ),
            enable_patch_policy=(
                task.enable_patch_policy
                if task.enable_patch_policy is not None
                else self.base_config.enable_patch_policy
            ),
            patch_policy_max_changed_files=(
                task.patch_policy_max_changed_files
                if task.patch_policy_max_changed_files is not None
                else self.base_config.patch_policy_max_changed_files
            ),
            patch_policy_max_total_changed_lines=(
                task.patch_policy_max_total_changed_lines
                if task.patch_policy_max_total_changed_lines is not None
                else self.base_config.patch_policy_max_total_changed_lines
            ),
            enable_failure_reflection=(
                task.enable_failure_reflection
                if task.enable_failure_reflection is not None
                else self.base_config.enable_failure_reflection
            ),
            max_reflection_retries=(
                task.max_reflection_retries
                if task.max_reflection_retries is not None
                else self.base_config.max_reflection_retries
            ),
            enable_retry_strategy_matrix=(
                task.enable_retry_strategy_matrix
                if task.enable_retry_strategy_matrix is not None
                else self.base_config.enable_retry_strategy_matrix
            ),
            enable_tool_planning_guidance=(
                task.enable_tool_planning_guidance
                if task.enable_tool_planning_guidance is not None
                else self.base_config.enable_tool_planning_guidance
            ),
        )
        config = _config_with_overrides(config, self.final_config_overrides)
        return _apply_benchmark_memory_policy(
            config,
            policy=self.memory_policy,
            run_dir=run_dir,
            task_id=task.task_id,
        )


class BenchmarkAblationRunner:
    """Runs one task set across named configuration variants."""

    def __init__(
        self,
        *,
        base_config: Config | None = None,
        registry: ToolRegistry | None = None,
        provider_factory: ProviderFactory | None = None,
        output_dir: str | Path = ".codeagentx/benchmarks",
        final_config_overrides: Mapping[str, Any] | None = None,
        memory_policy: str = "shared",
    ) -> None:
        self.base_config = (
            base_config if base_config is not None else Config.from_env()
        )
        self.registry = registry
        self.provider_factory = provider_factory
        self.output_dir = Path(output_dir)
        self.final_config_overrides = dict(final_config_overrides or {})
        self.memory_policy = _normalize_benchmark_memory_policy(memory_policy)

    def run(
        self,
        tasks: Iterable[BenchmarkTaskSpec],
        *,
        variants: Iterable[BenchmarkAblationVariant] | None = None,
        run_id: str | None = None,
    ) -> BenchmarkAblationReport:
        task_list = list(tasks)
        if not task_list:
            raise ValueError("benchmark ablation requires at least one task")

        variant_list = list(variants or default_ablation_variants())
        if not variant_list:
            raise ValueError("benchmark ablation requires at least one variant")
        _validate_variant_names(variant_list)

        run_id = run_id or _new_ablation_run_id()
        run_dir = self.output_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "tasks.json").write_text(
            json.dumps([task.to_dict() for task in task_list], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (run_dir / "variants.json").write_text(
            json.dumps([variant.to_dict() for variant in variant_list], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        variant_results = [
            self._run_variant(variant, task_list, run_dir=run_dir)
            for variant in variant_list
        ]
        report = BenchmarkAblationReport(
            run_id=run_id,
            created_at=_utc_now_iso(),
            output_dir=str(run_dir),
            tasks=task_list,
            variant_results=variant_results,
        )
        report.save()
        return report

    def _run_variant(
        self,
        variant: BenchmarkAblationVariant,
        tasks: list[BenchmarkTaskSpec],
        *,
        run_dir: Path,
    ) -> BenchmarkAblationVariantResult:
        report = BenchmarkRunner(
            base_config=self.base_config,
            registry=self.registry,
            provider_factory=self.provider_factory,
            output_dir=run_dir / "variants",
            final_config_overrides={
                **variant.overrides,
                **self.final_config_overrides,
            },
            memory_policy=self.memory_policy,
        ).run(tasks, run_id=_safe_variant_name(variant.name))
        return BenchmarkAblationVariantResult(variant=variant, report=report)


def load_benchmark_spec(path: str | Path) -> list[BenchmarkTaskSpec]:
    spec_path = Path(path)
    payload = json.loads(spec_path.read_text(encoding="utf-8"))

    if isinstance(payload, list):
        entries = payload
        defaults: Mapping[str, Any] = {}
    elif isinstance(payload, dict):
        entries = payload.get("tasks", [])
        defaults = payload.get("defaults", {})
    else:
        raise ValueError("benchmark spec must be a JSON object or array")

    if not isinstance(entries, list):
        raise ValueError("benchmark spec 'tasks' must be a list")

    return [
        BenchmarkTaskSpec.from_dict(
            entry,
            defaults=defaults,
            base_dir=spec_path.parent,
        )
        for entry in entries
    ]


def load_benchmark_ablation_spec(
    path: str | Path,
) -> tuple[list[BenchmarkTaskSpec], list[BenchmarkAblationVariant]]:
    spec_path = Path(path)
    payload = json.loads(spec_path.read_text(encoding="utf-8"))
    tasks = load_benchmark_spec(spec_path)

    variants_payload: Any = []
    if isinstance(payload, dict):
        variants_payload = payload.get(
            "ablation_variants",
            payload.get("variants", []),
        )
    if variants_payload in (None, "", []):
        return tasks, default_ablation_variants()
    if not isinstance(variants_payload, list):
        raise ValueError("benchmark spec 'ablation_variants' must be a list")

    return tasks, [
        BenchmarkAblationVariant.from_dict(variant)
        for variant in variants_payload
    ]


def default_ablation_variants() -> list[BenchmarkAblationVariant]:
    return [
        BenchmarkAblationVariant(
            name="baseline",
            description="All configured modules enabled.",
        ),
        BenchmarkAblationVariant(
            name="no_runtime_planning",
            description="Disable runtime task plan lifecycle tracking.",
            overrides={"enable_runtime_planning": False},
        ),
        BenchmarkAblationVariant(
            name="no_context_ranking",
            description="Disable ranked context injection before reflection retry.",
            overrides={"enable_context_ranking": False},
        ),
        BenchmarkAblationVariant(
            name="no_long_term_memory",
            description="Disable verified trajectory memory retrieval and extraction.",
            overrides={"enable_long_term_memory": False},
        ),
        BenchmarkAblationVariant(
            name="no_failure_reflection",
            description="Disable deterministic failure reflection and automatic retry.",
            overrides={
                "enable_failure_reflection": False,
                "max_reflection_retries": 0,
            },
        ),
        BenchmarkAblationVariant(
            name="no_retry_strategy_matrix",
            description="Keep retry, but remove strategy-specific guidance from retry prompts.",
            overrides={"enable_retry_strategy_matrix": False},
        ),
        BenchmarkAblationVariant(
            name="no_tool_planning_guidance",
            description="Keep retry strategy prompts, but disable runtime tool guidance.",
            overrides={"enable_tool_planning_guidance": False},
        ),
        BenchmarkAblationVariant(
            name="no_task_constraints",
            description="Disable deterministic task boundary checks.",
            overrides={"enable_task_constraints": False},
        ),
        BenchmarkAblationVariant(
            name="no_patch_policy",
            description="Disable patch policy quality gates.",
            overrides={"enable_patch_policy": False},
        ),
    ]


def _config_with_overrides(config: Config, overrides: Mapping[str, Any]) -> Config:
    if not overrides:
        return config

    config_fields = {item.name for item in fields(Config)}
    values: dict[str, Any] = {}
    for key, value in overrides.items():
        if key not in config_fields:
            raise ValueError(f"unknown Config override for ablation variant: {key}")
        if key == "permission_mode":
            values[key] = _coerce_permission_mode(value)
        else:
            values[key] = value
    return replace(config, **values)


def _variant_summary(report: BenchmarkReport) -> dict[str, Any]:
    return _report_summary(report)


def _report_summary(report: BenchmarkReport) -> dict[str, Any]:
    first_pass_successes = [
        result
        for result in report.results
        if result.resolved
        and int(result.metrics.get("reflection_retry_count", 0) or 0) == 0
    ]
    retry_recoveries = [
        result
        for result in report.results
        if result.resolved
        and int(result.metrics.get("reflection_retry_count", 0) or 0) > 0
    ]
    retry_attempted = [
        result
        for result in report.results
        if int(result.metrics.get("reflection_retry_count", 0) or 0) > 0
    ]

    return {
        "total_tasks": report.total_tasks,
        "resolved_tasks": report.resolved_tasks,
        "failed_tasks": report.failed_tasks,
        "resolved_rate": report.resolved_rate,
        "first_pass_success_tasks": len(first_pass_successes),
        "first_pass_success_rate": _ratio(len(first_pass_successes), report.total_tasks),
        "retry_attempted_tasks": len(retry_attempted),
        "retry_recovered_tasks": len(retry_recoveries),
        "retry_recovery_rate": _ratio(len(retry_recoveries), len(retry_attempted)),
        "duration_seconds": round(
            sum(result.duration_seconds for result in report.results),
            6,
        ),
        "average_turns": report._average_metric("turns"),
        "average_tool_calls": report._average_metric("tool_calls"),
        "average_budget_turns": report._average_metric("budget_turns"),
        "average_budget_tool_calls": report._average_metric("budget_tool_calls"),
        "average_budget_input_tokens": report._average_metric("budget_input_tokens"),
        "average_budget_output_tokens": report._average_metric("budget_output_tokens"),
        "average_budget_total_tokens": report._average_metric("budget_total_tokens"),
        "average_budget_elapsed_seconds": report._average_metric(
            "budget_elapsed_seconds"
        ),
        "budget_exhausted_tasks": sum(
            1 for result in report.results if result.metrics.get("budget_exhausted")
        ),
        "average_patch_changed_files": report._average_metric("patch_policy_changed_files"),
        "average_patch_changed_lines": report._average_metric("patch_policy_changed_lines"),
            "average_git_diff_patch_bytes": report._average_metric("git_diff_patch_bytes"),
            "average_git_diff_changed_files": report._average_metric("git_diff_changed_files"),
            "average_git_diff_forbidden_paths": report._average_metric(
                "git_diff_forbidden_path_count"
            ),
            "average_memory_hits": report._average_metric("memory_hit_count"),
        "average_memory_candidates": report._average_metric("memory_candidate_count"),
        "average_memory_filtered": report._average_metric("memory_filtered_count"),
        "average_memory_prompt_injected": report._average_metric(
            "memory_prompt_injected_count"
        ),
        "average_memory_stored": report._average_metric("memory_stored_count"),
        "artifact_count": sum(len(result.artifacts) for result in report.results),
        "metric_averages": _metric_averages(report.results),
    }


def _metric_averages(results: list[BenchmarkTaskResult]) -> dict[str, float]:
    return {
        key: _average_result_metric(results, key)
        for key in ABLATION_AVERAGE_METRICS
    }


def _average_result_metric(results: list[BenchmarkTaskResult], key: str) -> float:
    values = [
        result.metrics[key]
        for result in results
        if isinstance(result.metrics.get(key), (int, float))
    ]
    if not values:
        return 0.0
    return round(sum(values) / len(values), 6)


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 6)


def _delta_vs_baseline(
    baseline: Mapping[str, Any],
    current: Mapping[str, Any],
) -> dict[str, Any]:
    baseline_averages = baseline.get("metric_averages", {})
    current_averages = current.get("metric_averages", {})
    metric_deltas: dict[str, float] = {}
    if isinstance(baseline_averages, Mapping) and isinstance(current_averages, Mapping):
        for key, value in current_averages.items():
            baseline_value = baseline_averages.get(key)
            if isinstance(value, (int, float)) and isinstance(baseline_value, (int, float)):
                metric_deltas[str(key)] = round(value - baseline_value, 6)

    return {
        "resolved_rate": round(
            float(current.get("resolved_rate", 0.0) or 0.0)
            - float(baseline.get("resolved_rate", 0.0) or 0.0),
            6,
        ),
        "first_pass_success_rate": round(
            float(current.get("first_pass_success_rate", 0.0) or 0.0)
            - float(baseline.get("first_pass_success_rate", 0.0) or 0.0),
            6,
        ),
        "retry_recovery_rate": round(
            float(current.get("retry_recovery_rate", 0.0) or 0.0)
            - float(baseline.get("retry_recovery_rate", 0.0) or 0.0),
            6,
        ),
        "resolved_tasks": int(current.get("resolved_tasks", 0) or 0)
        - int(baseline.get("resolved_tasks", 0) or 0),
        "first_pass_success_tasks": int(current.get("first_pass_success_tasks", 0) or 0)
        - int(baseline.get("first_pass_success_tasks", 0) or 0),
        "retry_recovered_tasks": int(current.get("retry_recovered_tasks", 0) or 0)
        - int(baseline.get("retry_recovered_tasks", 0) or 0),
        "metric_averages": metric_deltas,
    }


def _task_outcome_matrix(
    variant_results: list[BenchmarkAblationVariantResult],
    tasks: list[BenchmarkTaskSpec],
) -> list[dict[str, Any]]:
    if not variant_results:
        return []

    baseline_name = variant_results[0].variant.name
    baseline_by_task = _results_by_task(variant_results[0].report)
    result_maps = [
        (variant_result.variant.name, _results_by_task(variant_result.report))
        for variant_result in variant_results
    ]

    matrix: list[dict[str, Any]] = []
    for task in tasks:
        baseline = baseline_by_task.get(task.task_id)
        baseline_resolved = bool(baseline.resolved) if baseline is not None else False
        outcomes: dict[str, Any] = {}
        improved: list[str] = []
        regressed: list[str] = []

        for variant_name, by_task in result_maps:
            result = by_task.get(task.task_id)
            outcome = _task_outcome_payload(result)
            outcomes[variant_name] = outcome
            if variant_name == baseline_name or result is None:
                continue
            if not baseline_resolved and result.resolved:
                improved.append(variant_name)
            if baseline_resolved and not result.resolved:
                regressed.append(variant_name)

        matrix.append({
            "task_id": task.task_id,
            "baseline_resolved": baseline_resolved,
            "outcomes": outcomes,
            "improved_variants": improved,
            "regressed_variants": regressed,
        })
    return matrix


def _results_by_task(report: BenchmarkReport) -> dict[str, BenchmarkTaskResult]:
    return {result.task_id: result for result in report.results}


def _task_outcome_payload(result: BenchmarkTaskResult | None) -> dict[str, Any]:
    if result is None:
        return {
            "resolved": False,
            "status": "missing",
            "verification_status": None,
        }
    return {
        "resolved": result.resolved,
        "status": result.status,
        "verification_status": result.verification_status,
        "tool_calls": result.metrics.get("tool_calls"),
        "failed_tool_calls": result.metrics.get("failed_tool_calls"),
        "reflection_retry_count": result.metrics.get("reflection_retry_count"),
        "memory_hit_count": result.metrics.get("memory_hit_count"),
        "tool_planning_guidance_blocked": result.metrics.get(
            "tool_planning_guidance_blocked"
        ),
    }


def _best_variant_name(results: list[BenchmarkAblationVariantResult]) -> str | None:
    if not results:
        return None
    best = max(
        results,
        key=lambda result: (
            result.report.resolved_rate,
            -_average_result_metric(result.report.results, "tool_calls"),
        ),
    )
    return best.variant.name


def _validate_variant_names(variants: list[BenchmarkAblationVariant]) -> None:
    seen_names: set[str] = set()
    seen_paths: set[str] = set()
    for variant in variants:
        if variant.name in seen_names:
            raise ValueError(f"duplicate ablation variant name: {variant.name}")
        seen_names.add(variant.name)

        path_name = _safe_variant_name(variant.name)
        if path_name in seen_paths:
            raise ValueError(f"duplicate ablation variant path name: {path_name}")
        seen_paths.add(path_name)


def _safe_variant_name(name: str) -> str:
    chars = [
        char.lower()
        if char.isalnum() or char in ("-", "_", ".")
        else "-"
        for char in str(name).strip()
    ]
    safe = "".join(chars).strip("-._")
    return safe or "variant"


def _prepare_task_workspace(
    source_workspace: Path,
    *,
    run_dir: Path,
    task_id: str,
    preserve_git_metadata: bool = False,
) -> Path:
    if not source_workspace.exists():
        raise ValueError(f"benchmark workspace does not exist: {source_workspace}")
    if not source_workspace.is_dir():
        raise ValueError(f"benchmark workspace is not a directory: {source_workspace}")

    workspace_dir = run_dir / "workspaces" / _safe_variant_name(task_id)
    if workspace_dir.exists():
        shutil.rmtree(workspace_dir)
    workspace_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        source_workspace,
        workspace_dir,
        ignore=_benchmark_copy_ignore(
            run_dir.resolve(),
            preserve_git_metadata=preserve_git_metadata,
        ),
    )
    return workspace_dir.resolve()


def _benchmark_copy_ignore(run_dir: Path, *, preserve_git_metadata: bool = False):
    patterns = [
        ".codeagentx",
        "__pycache__",
        ".pytest_cache",
        "*.pyc",
        "*.pyo",
    ]
    if not preserve_git_metadata:
        patterns.append(".git")

    def ignore(directory: str, names: list[str]) -> set[str]:
        ignored: set[str] = set()
        current = Path(directory)
        for name in names:
            candidate = (current / name).resolve()
            if any(fnmatch(name, pattern) for pattern in patterns):
                ignored.add(name)
                continue
            if candidate == run_dir or candidate in run_dir.parents:
                ignored.add(name)
        return ignored

    return ignore


def _run_command(
    command: str,
    *,
    cwd: str,
    timeout_seconds: int,
    config: Config,
    artifact_kind: str,
    task_id: str,
) -> BenchmarkCommandResult:
    result = create_sandbox_runner(config).run(
        command,
        spec=SandboxSpec(
            workspace_root=cwd,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            max_output_chars=MAX_RECORDED_OUTPUT_CHARS,
            sandbox_type=config.verification_sandbox,
        ),
    )
    artifacts: dict[str, Any] = {}
    if getattr(config, "enable_sandbox_artifacts", True) and config.sandbox_artifact_dir:
        artifacts = write_sandbox_artifacts(
            result,
            config.sandbox_artifact_dir,
            kind=artifact_kind,
            task_id=task_id,
            snapshot_max_files=getattr(config, "sandbox_snapshot_max_files", 2_000),
            snapshot_max_recorded_files=getattr(
                config,
                "sandbox_snapshot_max_recorded_files",
                100,
            ),
        )
    return BenchmarkCommandResult(
        command=command,
        exit_code=result.exit_code,
        stdout=result.stdout,
        stderr=result.stderr,
        duration_seconds=round(result.duration_ms / 1000, 6),
        timed_out=result.timed_out,
        sandbox=result.summary_dict(),
        artifacts=artifacts,
    )


def _benchmark_artifact_root(base_artifact_dir: str | None, *, run_dir: Path) -> Path:
    if base_artifact_dir:
        return Path(base_artifact_dir).expanduser() / run_dir.name
    return run_dir / "artifacts"


def _normalize_benchmark_memory_policy(policy: str | None) -> str:
    normalized = str(policy or "shared").strip().lower().replace("-", "_")
    aliases = {
        "off": "disabled",
        "none": "disabled",
        "disable": "disabled",
        "reset": "isolated",
        "per_task": "isolated",
        "per-task": "isolated",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in BENCHMARK_MEMORY_POLICIES:
        allowed = ", ".join(sorted(BENCHMARK_MEMORY_POLICIES))
        raise ValueError(
            f"unsupported benchmark memory policy {policy!r}; expected one of: {allowed}"
        )
    return normalized


def _benchmark_memory_policy_payload(
    policy: str,
    *,
    results: list[BenchmarkTaskResult] | None = None,
) -> dict[str, Any]:
    descriptions = {
        "shared": (
            "All tasks in the benchmark run share one memory store. This permits "
            "cross-task learning and is intended for local transfer experiments."
        ),
        "isolated": (
            "Each task receives an isolated memory store. This prevents cross-task "
            "learning while keeping memory instrumentation enabled."
        ),
        "disabled": (
            "Long-term memory is disabled for all benchmark tasks. This is the "
            "safest policy for public benchmark reporting."
        ),
    }
    payload: dict[str, Any] = {
        "policy": policy,
        "store_scope": {
            "shared": "run",
            "isolated": "task",
            "disabled": "none",
        }[policy],
        "cross_task_reuse": policy == "shared",
        "evaluation_leakage_risk": "possible" if policy == "shared" else "controlled",
        "description": descriptions[policy],
    }
    if results is not None:
        payload["memory_enabled_task_count"] = sum(
            1
            for result in results
            if result.metrics.get("memory_retrieval_count")
            or result.metrics.get("memory_extraction_count")
        )
        payload["memory_prompt_injected_task_count"] = sum(
            1
            for result in results
            if result.metrics.get("memory_prompt_injected_count")
        )
        payload["memory_stored_task_count"] = sum(
            1
            for result in results
            if result.metrics.get("memory_stored_count")
        )
    return payload


def _apply_benchmark_memory_policy(
    config: Config,
    *,
    policy: str,
    run_dir: Path,
    task_id: str,
) -> Config:
    policy = _normalize_benchmark_memory_policy(policy)
    if policy == "disabled":
        return replace(
            config,
            enable_long_term_memory=False,
            memory_store_path=None,
        )
    if not config.enable_long_term_memory:
        return replace(config, memory_store_path=None)
    return replace(
        config,
        memory_store_path=_benchmark_memory_store_path(
            config.memory_store_path,
            run_dir=run_dir,
            task_id=task_id,
            enabled=True,
            policy=policy,
        ),
    )


def _benchmark_memory_store_path(
    base_memory_store_path: str | None,
    *,
    run_dir: Path,
    task_id: str,
    enabled: bool,
    policy: str = "shared",
) -> str | None:
    if not enabled:
        return None
    policy = _normalize_benchmark_memory_policy(policy)
    if policy == "disabled":
        return None
    if policy == "isolated":
        return str(run_dir / "memory" / _safe_variant_name(task_id) / "memories.jsonl")
    if not base_memory_store_path:
        return str(run_dir / "memory" / "memories.jsonl")

    candidate = Path(base_memory_store_path).expanduser()
    if candidate.is_absolute():
        return str(candidate)
    if str(base_memory_store_path) == str(Config.memory_store_path):
        return str(run_dir / "memory" / "memories.jsonl")
    return str((run_dir / candidate).resolve())


def _artifact_index(
    *,
    setup_result: BenchmarkCommandResult | None,
    state: Any,
    git_diff_artifact: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    if setup_result is not None and setup_result.artifacts:
        artifacts.append(_compact_artifact(setup_result.artifacts))
    if state is not None:
        artifacts.extend(_verification_artifacts_from_state(state))
    if git_diff_artifact:
        artifacts.append(_compact_artifact(git_diff_artifact))
    return artifacts


def _verification_artifacts_from_state(state: Any) -> list[dict[str, Any]]:
    report = getattr(state, "verification_report", None)
    if not isinstance(report, dict):
        return []
    checks = report.get("checks", [])
    if not isinstance(checks, list):
        return []
    artifacts: list[dict[str, Any]] = []
    for check in checks:
        if not isinstance(check, dict) or check.get("name") != "verification_command":
            continue
        metadata = check.get("metadata", {})
        if not isinstance(metadata, dict):
            continue
        artifact = metadata.get("artifacts", {})
        if isinstance(artifact, dict) and artifact:
            artifacts.append(_compact_artifact(artifact))
    return artifacts


def _compact_artifact(artifact: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = artifact.get("workspace_snapshot", {})
    if not isinstance(snapshot, dict):
        snapshot = {}
    compact = {
        "artifact_id": artifact.get("artifact_id"),
        "kind": artifact.get("kind"),
        "task_id": artifact.get("task_id"),
        "artifact_dir": artifact.get("artifact_dir"),
        "stdout_path": artifact.get("stdout_path"),
        "stderr_path": artifact.get("stderr_path"),
        "result_path": artifact.get("result_path"),
        "manifest_path": artifact.get("manifest_path"),
        "workspace_sha256": snapshot.get("sha256"),
        "workspace_file_count": snapshot.get("fingerprinted_files"),
        "workspace_truncated": snapshot.get("truncated"),
    }
    if artifact.get("kind") == "git_diff":
        compact.update({
            "patch_path": artifact.get("patch_path"),
            "patch_bytes": artifact.get("patch_bytes"),
            "changed_files": list(artifact.get("changed_files") or []),
            "untracked_files": list(artifact.get("untracked_files") or []),
            "deleted_files": list(artifact.get("deleted_files") or []),
            "renamed_files": list(artifact.get("renamed_files") or []),
            "is_git_repository": artifact.get("is_git_repository"),
            "is_clean": artifact.get("is_clean"),
            "error": artifact.get("error"),
        })
    return compact


def _collect_task_git_diff_artifact(
    task: BenchmarkTaskSpec,
    *,
    run_workspace: Path,
    run_dir: Path,
    base_artifact_dir: str | None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if not task.enable_git_diff_artifact:
        return None, {}

    try:
        report = collect_git_diff(
            run_workspace,
            base_ref=task.git_diff_base_ref or task.repository_commit or "HEAD",
        )
        artifact = write_git_diff_artifacts(
            report,
            _benchmark_artifact_root(base_artifact_dir, run_dir=run_dir),
            task_id=task.task_id,
        )
    except Exception as exc:
        report = GitDiffReport(
            workspace_root=str(run_workspace),
            base_ref=task.git_diff_base_ref or task.repository_commit or "HEAD",
            is_git_repository=False,
            error=f"{exc.__class__.__name__}: {exc}",
        )
        artifact = None
    return artifact, _git_diff_metrics(
        report,
        forbidden_paths=task.forbidden_changed_paths,
    )


def _git_diff_metrics(
    report: GitDiffReport,
    *,
    forbidden_paths: Iterable[str] = (),
) -> dict[str, Any]:
    forbidden_patterns = [
        str(pattern).replace("\\", "/")
        for pattern in forbidden_paths
        if str(pattern).strip()
    ]
    forbidden_matches = _matching_git_diff_forbidden_paths(
        report.changed_files,
        forbidden_patterns,
    )
    policy_status = "skipped"
    if forbidden_patterns:
        policy_status = "failed" if forbidden_matches else "passed"
    return {
        "git_diff_patch_bytes": report.patch_bytes,
        "git_diff_changed_files": len(report.changed_files),
        "git_diff_untracked_files": len(report.untracked_files),
        "git_diff_deleted_files": len(report.deleted_files),
        "git_diff_renamed_files": len(report.renamed_files),
        "git_diff_forbidden_path_count": len(forbidden_matches),
        "git_diff_forbidden_paths": forbidden_matches,
        "git_diff_forbidden_patterns": forbidden_patterns,
        "git_diff_policy_status": policy_status,
        "git_diff_is_git_repository": report.is_git_repository,
        "git_diff_is_clean": report.is_clean,
        "git_diff_error": report.error,
    }


def _git_diff_policy_failed(metrics: Mapping[str, Any]) -> bool:
    count = metrics.get("git_diff_forbidden_path_count")
    return isinstance(count, int) and count > 0


def _matching_git_diff_forbidden_paths(
    changed_paths: Iterable[str],
    patterns: Iterable[str],
) -> list[str]:
    normalized_patterns = [pattern.rstrip("/") for pattern in patterns]
    matches: list[str] = []
    for raw_path in changed_paths:
        path = str(raw_path).replace("\\", "/")
        name = Path(path).name
        if any(
            fnmatch(path, pattern) or fnmatch(name, pattern)
            for pattern in normalized_patterns
        ):
            matches.append(path)
    return sorted(set(matches))


def _state_path(agent: AgentLoop, state: Any) -> str | None:
    if state is None or agent.trajectory_store is None:
        return None
    return str(agent.trajectory_store.state_path(state.task_id))


def _events_path(agent: AgentLoop, state: Any) -> str | None:
    if state is None or agent.trajectory_store is None:
        return None
    return str(agent.trajectory_store.events_path(state.task_id))


def _verification_status(metrics: Mapping[str, Any]) -> str | None:
    value = metrics.get("verification_status")
    return str(value) if value is not None else None


def _coerce_permission_mode(value: Any) -> PermissionMode | None:
    if value is None or value == "":
        return None
    if isinstance(value, PermissionMode):
        return value
    return PermissionMode(str(value))


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _optional_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in ("1", "true", "yes", "y", "on"):
        return True
    if normalized in ("0", "false", "no", "n", "off"):
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


def _resolve_maybe_relative(path: str, base_dir: Path) -> str:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return str(candidate)
    return str((base_dir / candidate).resolve())


def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"bench-{stamp}-{uuid4().hex[:8]}"


def _new_ablation_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"ablation-{stamp}-{uuid4().hex[:8]}"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _elapsed(started: float) -> float:
    return round(time.perf_counter() - started, 6)


def _truncate(value: Any, max_chars: int = MAX_RECORDED_OUTPUT_CHARS) -> str:
    if value is None:
        value = ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if not isinstance(value, str):
        value = str(value)
    if len(value) <= max_chars:
        return value
    omitted = len(value) - max_chars
    return value[:max_chars] + f"\n... output truncated {omitted} chars"
