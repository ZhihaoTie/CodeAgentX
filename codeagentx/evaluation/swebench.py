"""SWE-bench task loading and conversion helpers."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

from .benchmark import BenchmarkTaskSpec


DEFAULT_SWEBENCH_REPO_URL_TEMPLATE = "https://github.com/{repo}.git"
DEFAULT_SWEBENCH_WORKSPACES_ROOT = ".codeagentx/swebench/workspaces"
DEFAULT_SWEBENCH_REPO_CACHE_ROOT = ".codeagentx/swebench/repos"
SWEBENCH_TASK_MANIFEST_SCHEMA_VERSION = "codeagentx.swebench_task_manifest.v1"
MAX_SWEBENCH_COMMAND_OUTPUT_CHARS = 12_000
SWEBENCH_FORBIDDEN_SCRATCH_PATHS = [
    "test_fix.py",
    "test_*_fix.py",
    "scratch.py",
    "scratch_*.py",
    "debug.py",
    "debug_*.py",
    "repro.py",
    "repro_*.py",
    "tmp.py",
    "tmp_*.py",
    "temp.py",
    "temp_*.py",
]


@dataclass(frozen=True)
class SWEbenchTaskSpec:
    """A minimal SWE-bench task model safe to convert into an agent task."""

    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str
    fail_to_pass: list[str] = field(default_factory=list)
    pass_to_pass: list[str] = field(default_factory=list)
    version: str | None = None
    environment: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SWEbenchTaskSpec":
        instance_id = payload.get("instance_id", payload.get("id"))
        repo = payload.get("repo", payload.get("repository"))
        base_commit = payload.get("base_commit", payload.get("commit"))
        problem_statement = payload.get("problem_statement", payload.get("issue"))

        if not instance_id:
            raise ValueError("SWE-bench task is missing 'instance_id'")
        if not repo:
            raise ValueError(f"SWE-bench task {instance_id!r} is missing 'repo'")
        if not base_commit:
            raise ValueError(f"SWE-bench task {instance_id!r} is missing 'base_commit'")
        if not problem_statement:
            raise ValueError(
                f"SWE-bench task {instance_id!r} is missing 'problem_statement'"
            )

        known_keys = {
            "instance_id",
            "id",
            "repo",
            "repository",
            "base_commit",
            "commit",
            "problem_statement",
            "issue",
            "FAIL_TO_PASS",
            "PASS_TO_PASS",
            "fail_to_pass",
            "pass_to_pass",
            "version",
            "environment",
        }
        metadata = {
            key: value
            for key, value in payload.items()
            if key not in known_keys and key != "patch"
        }

        return cls(
            instance_id=str(instance_id),
            repo=str(repo),
            base_commit=str(base_commit),
            problem_statement=str(problem_statement),
            fail_to_pass=_string_list(payload.get("FAIL_TO_PASS", payload.get("fail_to_pass"))),
            pass_to_pass=_string_list(payload.get("PASS_TO_PASS", payload.get("pass_to_pass"))),
            version=_optional_str(payload.get("version")),
            environment=dict(payload.get("environment") or {}),
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "repo": self.repo,
            "base_commit": self.base_commit,
            "problem_statement": self.problem_statement,
            "FAIL_TO_PASS": list(self.fail_to_pass),
            "PASS_TO_PASS": list(self.pass_to_pass),
            "version": self.version,
            "environment": dict(self.environment),
            "metadata": dict(self.metadata),
        }

    def to_agent_goal(self) -> str:
        """Build the prompt visible to CodeAgent-X.

        Evaluation-only test metadata stays out of the prompt so the agent does
        not receive official grading targets as hints.
        """

        return "\n".join([
            "Fix the following SWE-bench issue in the checked-out repository.",
            "",
            f"Repository: {self.repo}",
            f"Base commit: {self.base_commit}",
            "",
            "Issue:",
            self.problem_statement.strip(),
            "",
            "Requirements:",
            "- Modify the repository to resolve the issue.",
            "- Do not use or rely on any gold patch.",
            "- Keep changes minimal and run relevant tests when possible.",
            "- Do not leave ad-hoc scratch, debug, or reproduction scripts in the final diff.",
            "- If you create temporary verification files, delete them before finishing.",
            "- Return a concise summary of the fix and verification.",
        ])

    def to_benchmark_task(
        self,
        *,
        workspace_root: str | Path,
        verification_command: str | None = None,
        setup_command: str | None = None,
        tags: list[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> BenchmarkTaskSpec:
        merged_metadata = {
            "swebench": {
                "instance_id": self.instance_id,
                "repo": self.repo,
                "base_commit": self.base_commit,
                "FAIL_TO_PASS": list(self.fail_to_pass),
                "PASS_TO_PASS": list(self.pass_to_pass),
                "version": self.version,
                "environment": dict(self.environment),
                "metadata": dict(self.metadata),
            }
        }
        if metadata:
            merged_metadata.update(dict(metadata))

        task_tags = ["swe-bench", "real-issue", *list(tags or [])]
        return BenchmarkTaskSpec(
            task_id=self.instance_id,
            goal=self.to_agent_goal(),
            workspace_root=str(workspace_root),
            verification_command=verification_command,
            setup_command=setup_command,
            repository_commit=self.base_commit,
            enable_git_diff_artifact=True,
            git_diff_base_ref=self.base_commit,
            success_criteria=[
                "The official SWE-bench evaluator marks the generated patch as resolved.",
                "The generated patch is collected from git diff after the agent run.",
            ],
            forbidden_changed_paths=list(SWEBENCH_FORBIDDEN_SCRATCH_PATHS),
            tags=_unique(task_tags),
            metadata=merged_metadata,
        )


@dataclass(frozen=True)
class SWEbenchTaskManifestEntry:
    """Dry-run metadata for one SWE-bench task before workspace provisioning."""

    instance_id: str
    repo: str
    base_commit: str
    version: str | None
    fail_to_pass_count: int
    pass_to_pass_count: int
    problem_statement_chars: int
    problem_statement_sha256: str
    agent_goal_chars: int
    agent_goal_sha256: str
    prompt_contains_grader_tests: bool = False
    visible_grader_test_count: int = 0
    estimated_workspace_root: str | None = None
    environment_keys: list[str] = field(default_factory=list)
    metadata_keys: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "repo": self.repo,
            "base_commit": self.base_commit,
            "version": self.version,
            "fail_to_pass_count": self.fail_to_pass_count,
            "pass_to_pass_count": self.pass_to_pass_count,
            "problem_statement_chars": self.problem_statement_chars,
            "problem_statement_sha256": self.problem_statement_sha256,
            "agent_goal_chars": self.agent_goal_chars,
            "agent_goal_sha256": self.agent_goal_sha256,
            "prompt_contains_grader_tests": self.prompt_contains_grader_tests,
            "visible_grader_test_count": self.visible_grader_test_count,
            "estimated_workspace_root": self.estimated_workspace_root,
            "environment_keys": list(self.environment_keys),
            "metadata_keys": list(self.metadata_keys),
        }


@dataclass(frozen=True)
class SWEbenchTaskManifest:
    """A no-provisioning SWE-bench task selection manifest."""

    source_path: str | None
    task_count: int
    entries: list[SWEbenchTaskManifestEntry]
    manifest_path: str | None = None
    selected_task_ids: list[str] = field(default_factory=list)
    limit: int | None = None
    workspaces_root: str | None = None

    @property
    def repositories(self) -> list[str]:
        return sorted({entry.repo for entry in self.entries})

    @property
    def versions(self) -> list[str]:
        return sorted({entry.version for entry in self.entries if entry.version})

    @property
    def total_fail_to_pass(self) -> int:
        return sum(entry.fail_to_pass_count for entry in self.entries)

    @property
    def total_pass_to_pass(self) -> int:
        return sum(entry.pass_to_pass_count for entry in self.entries)

    @property
    def prompt_leakage_count(self) -> int:
        return sum(1 for entry in self.entries if entry.prompt_contains_grader_tests)

    @property
    def task_ids(self) -> list[str]:
        return [entry.instance_id for entry in self.entries]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SWEBENCH_TASK_MANIFEST_SCHEMA_VERSION,
            "source_path": self.source_path,
            "manifest_path": self.manifest_path,
            "task_count": self.task_count,
            "task_ids": list(self.task_ids),
            "repositories": list(self.repositories),
            "versions": list(self.versions),
            "selection": {
                "task_ids": list(self.selected_task_ids),
                "limit": self.limit,
            },
            "workspace_plan": {
                "workspaces_root": self.workspaces_root,
                "provisioning_performed": False,
            },
            "leakage_guard": {
                "fail_to_pass_hidden_from_prompt": self.prompt_leakage_count == 0,
                "pass_to_pass_hidden_from_prompt": self.prompt_leakage_count == 0,
                "prompt_leakage_task_count": self.prompt_leakage_count,
            },
            "test_target_totals": {
                "FAIL_TO_PASS": self.total_fail_to_pass,
                "PASS_TO_PASS": self.total_pass_to_pass,
            },
            "entries": [entry.to_dict() for entry in self.entries],
        }


@dataclass(frozen=True)
class SWEbenchGitCommandResult:
    """A recorded git command executed during workspace provisioning."""

    argv: list[str]
    cwd: str
    exit_code: int | None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def to_dict(self) -> dict[str, Any]:
        return {
            "argv": list(self.argv),
            "cwd": self.cwd,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
            "passed": self.passed,
        }


@dataclass(frozen=True)
class SWEbenchWorkspaceReport:
    """Provisioning evidence for a checked-out SWE-bench workspace."""

    instance_id: str
    repo: str
    repo_url: str
    base_commit: str
    workspace_root: str
    cache_root: str | None = None
    cache_path: str | None = None
    cache_reused: bool = False
    cache_refreshed: bool = False
    overwrite_existing: bool = True
    submodules_updated: bool = False
    head_commit: str | None = None
    commands: list[SWEbenchGitCommandResult] = field(default_factory=list)

    @property
    def prepared(self) -> bool:
        return self.head_commit == self.base_commit

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "repo": self.repo,
            "repo_url": self.repo_url,
            "base_commit": self.base_commit,
            "workspace_root": self.workspace_root,
            "cache_root": self.cache_root,
            "cache_path": self.cache_path,
            "cache_reused": self.cache_reused,
            "cache_refreshed": self.cache_refreshed,
            "overwrite_existing": self.overwrite_existing,
            "submodules_updated": self.submodules_updated,
            "head_commit": self.head_commit,
            "prepared": self.prepared,
            "commands": [command.to_dict() for command in self.commands],
        }


class SWEbenchWorkspaceProvisioner:
    """Prepare isolated git workspaces for SWE-bench style tasks.

    The provisioner keeps a local bare mirror cache by default, then clones from
    that cache into a per-instance workspace and checks out the task base commit.
    """

    def __init__(
        self,
        *,
        workspaces_root: str | Path = DEFAULT_SWEBENCH_WORKSPACES_ROOT,
        repo_cache_root: str | Path | None = DEFAULT_SWEBENCH_REPO_CACHE_ROOT,
        repo_url_template: str = DEFAULT_SWEBENCH_REPO_URL_TEMPLATE,
        git_binary: str = "git",
        timeout_seconds: int = 300,
        overwrite_existing: bool = True,
        refresh_cache: bool = False,
        update_submodules: bool = False,
    ) -> None:
        self.workspaces_root = Path(workspaces_root).expanduser().resolve(strict=False)
        self.repo_cache_root = (
            Path(repo_cache_root).expanduser().resolve(strict=False)
            if repo_cache_root is not None
            else None
        )
        self.repo_url_template = repo_url_template
        self.git_binary = git_binary
        self.timeout_seconds = timeout_seconds
        self.overwrite_existing = overwrite_existing
        self.refresh_cache = refresh_cache
        self.update_submodules = update_submodules

    def prepare_task(self, task: SWEbenchTaskSpec) -> SWEbenchWorkspaceReport:
        """Clone or refresh a task workspace at its base commit."""

        commands: list[SWEbenchGitCommandResult] = []
        repo_url = self.repo_url_for(task.repo)
        workspace = self.workspace_path_for(task)
        cache_path = self.cache_path_for(task.repo) if self.repo_cache_root else None
        cache_reused = False
        cache_refreshed = False

        self.workspaces_root.mkdir(parents=True, exist_ok=True)
        if self.repo_cache_root is not None:
            self.repo_cache_root.mkdir(parents=True, exist_ok=True)

        clone_source = repo_url
        if cache_path is not None:
            if cache_path.exists():
                cache_reused = True
                if self.refresh_cache:
                    cache_refreshed = True
                    commands.append(
                        self._git(["remote", "update", "--prune"], cwd=cache_path)
                    )
                    _require_passed(commands[-1], "refresh SWE-bench repository cache")
            else:
                commands.append(
                    self._git(
                        ["clone", "--mirror", repo_url, str(cache_path)],
                        cwd=self.repo_cache_root,
                    )
                )
                _require_passed(commands[-1], "clone SWE-bench repository cache")
            clone_source = str(cache_path)

        if workspace.exists():
            if not self.overwrite_existing:
                raise ValueError(
                    f"SWE-bench workspace already exists: {workspace}. "
                    "Set overwrite_existing=True to recreate it."
                )
            _remove_tree_under(workspace, self.workspaces_root)

        commands.append(
            self._git(["clone", clone_source, str(workspace)], cwd=self.workspaces_root)
        )
        _require_passed(commands[-1], "clone SWE-bench task workspace")

        commands.append(
            self._git(["checkout", "--force", task.base_commit], cwd=workspace)
        )
        if not commands[-1].passed and cache_path is not None and cache_reused and not cache_refreshed:
            cache_refreshed = True
            commands.append(self._git(["remote", "update", "--prune"], cwd=cache_path))
            _require_passed(commands[-1], "refresh SWE-bench repository cache")
            commands.append(
                self._git(["fetch", "--all", "--tags", "--prune"], cwd=workspace)
            )
            _require_passed(commands[-1], "fetch refreshed SWE-bench workspace refs")
            commands.append(
                self._git(["checkout", "--force", task.base_commit], cwd=workspace)
            )
        _require_passed(commands[-1], "checkout SWE-bench base commit")

        commands.append(self._git(["clean", "-fdx"], cwd=workspace))
        _require_passed(commands[-1], "clean SWE-bench task workspace")

        submodules_updated = False
        if self.update_submodules:
            commands.append(
                self._git(["submodule", "update", "--init", "--recursive"], cwd=workspace)
            )
            _require_passed(commands[-1], "update SWE-bench task submodules")
            submodules_updated = True

        commands.append(self._git(["rev-parse", "HEAD"], cwd=workspace))
        _require_passed(commands[-1], "read SWE-bench workspace HEAD")
        head_commit = commands[-1].stdout.strip()

        return SWEbenchWorkspaceReport(
            instance_id=task.instance_id,
            repo=task.repo,
            repo_url=repo_url,
            base_commit=task.base_commit,
            workspace_root=str(workspace),
            cache_root=str(self.repo_cache_root) if self.repo_cache_root else None,
            cache_path=str(cache_path) if cache_path else None,
            cache_reused=cache_reused,
            cache_refreshed=cache_refreshed,
            overwrite_existing=self.overwrite_existing,
            submodules_updated=submodules_updated,
            head_commit=head_commit,
            commands=commands,
        )

    def prepare_benchmark_task(
        self,
        task: SWEbenchTaskSpec,
        *,
        verification_command: str | None = None,
        setup_command: str | None = None,
        tags: list[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> BenchmarkTaskSpec:
        """Provision a workspace and return a runnable BenchmarkTaskSpec."""

        report = self.prepare_task(task)
        merged_metadata = {"swebench_workspace": report.to_dict()}
        if metadata:
            merged_metadata.update(dict(metadata))
        return task.to_benchmark_task(
            workspace_root=report.workspace_root,
            verification_command=verification_command,
            setup_command=setup_command,
            tags=tags,
            metadata=merged_metadata,
        )

    def prepare_benchmark_tasks(
        self,
        tasks: list[SWEbenchTaskSpec],
        *,
        verification_command: str | None = None,
        setup_command: str | None = None,
        tags: list[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> list[BenchmarkTaskSpec]:
        return [
            self.prepare_benchmark_task(
                task,
                verification_command=verification_command,
                setup_command=setup_command,
                tags=tags,
                metadata=metadata,
            )
            for task in tasks
        ]

    def workspace_path_for(self, task: SWEbenchTaskSpec) -> Path:
        return self.workspaces_root / _safe_slug(task.instance_id)

    def cache_path_for(self, repo: str) -> Path:
        if self.repo_cache_root is None:
            raise ValueError("SWE-bench repository cache is disabled")
        digest = sha256(repo.encode("utf-8", errors="replace")).hexdigest()[:10]
        return self.repo_cache_root / f"{_safe_slug(repo)}-{digest}.git"

    def repo_url_for(self, repo: str) -> str:
        local_path = Path(repo).expanduser()
        if local_path.exists():
            return str(local_path.resolve())
        if _looks_like_git_url(repo):
            return repo
        return self.repo_url_template.format(repo=repo)

    def _git(self, args: list[str], *, cwd: Path) -> SWEbenchGitCommandResult:
        argv = [self.git_binary, *args]
        try:
            result = subprocess.run(
                argv,
                cwd=cwd,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            return SWEbenchGitCommandResult(
                argv=argv,
                cwd=str(cwd),
                exit_code=None,
                stdout=_truncate(_coerce_text(exc.stdout)),
                stderr=_truncate(_coerce_text(exc.stderr)),
                timed_out=True,
            )
        except OSError as exc:
            return SWEbenchGitCommandResult(
                argv=argv,
                cwd=str(cwd),
                exit_code=None,
                stderr=f"{exc.__class__.__name__}: {exc}",
            )
        return SWEbenchGitCommandResult(
            argv=argv,
            cwd=str(cwd),
            exit_code=result.returncode,
            stdout=_truncate(result.stdout),
            stderr=_truncate(result.stderr),
        )


def load_swebench_tasks(
    path: str | Path,
    *,
    task_ids: list[str] | None = None,
    limit: int | None = None,
) -> list[SWEbenchTaskSpec]:
    """Load SWE-bench tasks from JSONL, JSON array, or JSON object payloads."""

    payloads = _load_payloads(Path(path))
    tasks = [SWEbenchTaskSpec.from_dict(payload) for payload in payloads]

    if task_ids:
        wanted = set(task_ids)
        tasks = [task for task in tasks if task.instance_id in wanted]
        missing = sorted(wanted - {task.instance_id for task in tasks})
        if missing:
            raise ValueError(f"unknown SWE-bench task id(s): {', '.join(missing)}")

    if limit is not None:
        if limit <= 0:
            raise ValueError("SWE-bench task limit must be greater than 0")
        tasks = tasks[:limit]

    if not tasks:
        raise ValueError("SWE-bench task filter selected no tasks")
    return tasks


def build_swebench_task_manifest(
    tasks: list[SWEbenchTaskSpec],
    *,
    source_path: str | Path | None = None,
    selected_task_ids: list[str] | None = None,
    limit: int | None = None,
    workspaces_root: str | Path | None = DEFAULT_SWEBENCH_WORKSPACES_ROOT,
    manifest_path: str | Path | None = None,
) -> SWEbenchTaskManifest:
    """Build a dry-run manifest for a selected SWE-bench task subset."""

    if not tasks:
        raise ValueError("cannot build a SWE-bench manifest for zero tasks")

    root = (
        Path(workspaces_root).expanduser().resolve(strict=False)
        if workspaces_root is not None
        else None
    )
    entries = [
        _manifest_entry_for_task(task, workspaces_root=root)
        for task in tasks
    ]
    return SWEbenchTaskManifest(
        source_path=str(source_path) if source_path is not None else None,
        manifest_path=str(manifest_path) if manifest_path is not None else None,
        task_count=len(entries),
        entries=entries,
        selected_task_ids=list(selected_task_ids or []),
        limit=limit,
        workspaces_root=str(root) if root is not None else None,
    )


def write_swebench_task_manifest(
    tasks: list[SWEbenchTaskSpec],
    output_path: str | Path,
    *,
    source_path: str | Path | None = None,
    selected_task_ids: list[str] | None = None,
    limit: int | None = None,
    workspaces_root: str | Path | None = DEFAULT_SWEBENCH_WORKSPACES_ROOT,
) -> SWEbenchTaskManifest:
    """Write a SWE-bench dry-run manifest without cloning or running the agent."""

    output = Path(output_path).expanduser()
    manifest = build_swebench_task_manifest(
        tasks,
        source_path=source_path,
        selected_task_ids=selected_task_ids,
        limit=limit,
        workspaces_root=workspaces_root,
        manifest_path=output,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def _manifest_entry_for_task(
    task: SWEbenchTaskSpec,
    *,
    workspaces_root: Path | None,
) -> SWEbenchTaskManifestEntry:
    agent_goal = task.to_agent_goal()
    visible_grader_test_count = _visible_grader_test_count(task, agent_goal)
    estimated_workspace_root = (
        str(workspaces_root / _safe_slug(task.instance_id))
        if workspaces_root is not None
        else None
    )
    return SWEbenchTaskManifestEntry(
        instance_id=task.instance_id,
        repo=task.repo,
        base_commit=task.base_commit,
        version=task.version,
        fail_to_pass_count=len(task.fail_to_pass),
        pass_to_pass_count=len(task.pass_to_pass),
        problem_statement_chars=len(task.problem_statement),
        problem_statement_sha256=_sha256_text(task.problem_statement),
        agent_goal_chars=len(agent_goal),
        agent_goal_sha256=_sha256_text(agent_goal),
        prompt_contains_grader_tests=visible_grader_test_count > 0,
        visible_grader_test_count=visible_grader_test_count,
        estimated_workspace_root=estimated_workspace_root,
        environment_keys=sorted(str(key) for key in task.environment),
        metadata_keys=sorted(str(key) for key in task.metadata),
    )


def _visible_grader_test_count(task: SWEbenchTaskSpec, agent_goal: str) -> int:
    targets = [
        target
        for target in [*task.fail_to_pass, *task.pass_to_pass]
        if str(target).strip()
    ]
    return sum(1 for target in targets if str(target) in agent_goal)


def _sha256_text(value: str) -> str:
    return sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _load_payloads(path: Path) -> list[Mapping[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)

    if path.suffix.lower() == ".jsonl":
        payloads: list[Mapping[str, Any]] = []
        for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if not isinstance(payload, Mapping):
                raise ValueError(f"SWE-bench JSONL line {line_number} is not an object")
            payloads.append(payload)
        return payloads

    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return _mapping_list(payload)
    if isinstance(payload, Mapping):
        if isinstance(payload.get("instances"), list):
            return _mapping_list(payload["instances"])
        if isinstance(payload.get("tasks"), list):
            return _mapping_list(payload["tasks"])
        return [payload]
    raise ValueError("SWE-bench payload must be a JSON object, array, or JSONL file")


def _mapping_list(values: list[Any]) -> list[Mapping[str, Any]]:
    payloads: list[Mapping[str, Any]] = []
    for index, value in enumerate(values):
        if not isinstance(value, Mapping):
            raise ValueError(f"SWE-bench item {index} is not an object")
        payloads.append(value)
    return payloads


def _string_list(value: Any) -> list[str]:
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
    raise ValueError(f"expected string list, got {type(value).__name__}")


def _optional_str(value: Any) -> str | None:
    return None if value in (None, "") else str(value)


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _require_passed(result: SWEbenchGitCommandResult, action: str) -> None:
    if result.passed:
        return
    detail = result.stderr.strip() or result.stdout.strip() or "no command output"
    raise RuntimeError(
        f"failed to {action}: {' '.join(result.argv)} "
        f"(exit_code={result.exit_code}, timed_out={result.timed_out}): {detail}"
    )


def _remove_tree_under(path: Path, root: Path) -> None:
    resolved_path = path.resolve(strict=False)
    resolved_root = root.resolve(strict=False)
    if resolved_path == resolved_root or resolved_root not in resolved_path.parents:
        raise ValueError(f"refusing to remove path outside SWE-bench workspace root: {path}")
    shutil.rmtree(resolved_path, onerror=_make_writable_and_retry)


def _make_writable_and_retry(function: Any, path: str, exc_info: Any) -> None:
    try:
        os.chmod(path, stat.S_IWRITE)
        function(path)
    except OSError:
        raise exc_info[1]


def _looks_like_git_url(value: str) -> bool:
    return (
        "://" in value
        or value.startswith("git@")
        or value.startswith("ssh://")
        or value.endswith(".git")
    )


def _safe_slug(value: str) -> str:
    chars = [
        char.lower() if char.isalnum() or char in ("-", "_", ".") else "-"
        for char in str(value).strip()
    ]
    slug = "".join(chars).strip("-._")
    return slug or "item"


def _coerce_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _truncate(value: object, max_chars: int = MAX_SWEBENCH_COMMAND_OUTPUT_CHARS) -> str:
    text = _coerce_text(value)
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return text[:max_chars] + f"\n... output truncated {omitted} chars"
