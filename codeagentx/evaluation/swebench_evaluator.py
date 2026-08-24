"""SWE-bench prediction and official evaluator integration helpers."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


SWEBENCH_PREDICTIONS_SCHEMA_VERSION = "codeagentx.swebench_predictions.v1"
SWEBENCH_ANNOTATED_REPORT_SCHEMA_VERSION = "codeagentx.swebench_annotated_report.v1"
DEFAULT_SWEBENCH_DATASET_NAME = "SWE-bench/SWE-bench_Lite"
DEFAULT_SWEBENCH_SPLIT = "test"
MAX_EVALUATOR_OUTPUT_CHARS = 24_000


@dataclass(frozen=True)
class SWEbenchPrediction:
    """One SWE-bench-compatible patch prediction."""

    instance_id: str
    model_name_or_path: str
    model_patch: str

    @property
    def patch_generated(self) -> bool:
        return bool(self.model_patch.strip())

    @property
    def patch_bytes(self) -> int:
        return len(self.model_patch.encode("utf-8"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "model_name_or_path": self.model_name_or_path,
            "model_patch": self.model_patch,
        }


@dataclass(frozen=True)
class SWEbenchPredictionsArtifact:
    """Manifest for a generated SWE-bench predictions file."""

    predictions_path: str
    manifest_path: str
    source_report_path: str | None
    model_name_or_path: str
    prediction_count: int
    patch_generated_count: int
    empty_patch_count: int
    total_patch_bytes: int
    instance_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SWEBENCH_PREDICTIONS_SCHEMA_VERSION,
            "predictions_path": self.predictions_path,
            "manifest_path": self.manifest_path,
            "source_report_path": self.source_report_path,
            "model_name_or_path": self.model_name_or_path,
            "prediction_count": self.prediction_count,
            "patch_generated_count": self.patch_generated_count,
            "empty_patch_count": self.empty_patch_count,
            "total_patch_bytes": self.total_patch_bytes,
            "instance_ids": list(self.instance_ids),
        }


@dataclass(frozen=True)
class SWEbenchEvaluatorConfig:
    """Configuration for invoking the official SWE-bench evaluator."""

    dataset_name: str = DEFAULT_SWEBENCH_DATASET_NAME
    split: str = DEFAULT_SWEBENCH_SPLIT
    run_id: str = "codeagentx-swebench"
    max_workers: int = 4
    timeout_seconds: int = 1_800
    cache_level: str = "env"
    clean: bool = False
    namespace: str | None = "swebench"
    report_dir: str | None = None
    force_rebuild: bool = False
    rewrite_reports: bool = False
    modal: bool = False
    python_executable: str = sys.executable
    command_prefix: list[str] = field(default_factory=list)
    posix_paths: bool = False
    extra_args: list[str] = field(default_factory=list)

    def to_argv(
        self,
        predictions_path: str | Path,
        *,
        instance_ids: list[str] | None = None,
    ) -> list[str]:
        argv = [
            *self.command_prefix,
            self.python_executable,
            "-m",
            "swebench.harness.run_evaluation",
            "--dataset_name",
            self.dataset_name,
            "--split",
            self.split,
            "--predictions_path",
            self._path_arg(predictions_path),
            "--max_workers",
            str(self.max_workers),
            "--timeout",
            str(self.timeout_seconds),
            "--cache_level",
            self.cache_level,
            "--clean",
            _bool_arg(self.clean),
            "--run_id",
            self.run_id,
            "--force_rebuild",
            _bool_arg(self.force_rebuild),
            "--rewrite_reports",
            _bool_arg(self.rewrite_reports),
            "--modal",
            _bool_arg(self.modal),
        ]
        if self.namespace is not None:
            argv.extend(["--namespace", self.namespace])
        if self.report_dir:
            argv.extend(["--report_dir", self._path_arg(self.report_dir)])
        if instance_ids:
            argv.append("--instance_ids")
            argv.extend(instance_ids)
        argv.extend(self.extra_args)
        return argv

    def _path_arg(self, value: str | Path) -> str:
        text = str(value)
        return text.replace("\\", "/") if self.posix_paths else text


@dataclass(frozen=True)
class SWEbenchEvaluationResult:
    """Result of an official SWE-bench evaluator command."""

    command: list[str]
    exit_code: int | None
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
    timed_out: bool = False
    predictions_path: str | None = None
    run_id: str | None = None
    results_path: str | None = None
    instance_results_path: str | None = None

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": list(self.command),
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_seconds": self.duration_seconds,
            "timed_out": self.timed_out,
            "passed": self.passed,
            "predictions_path": self.predictions_path,
            "run_id": self.run_id,
            "results_path": self.results_path,
            "instance_results_path": self.instance_results_path,
        }


@dataclass(frozen=True)
class SWEbenchOfficialOutcome:
    """Resolved status extracted from an official SWE-bench result payload."""

    instance_id: str
    resolved: bool | None
    status: str = "unknown"
    error: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    tests_status: dict[str, Any] = field(default_factory=dict)
    patch_exists: bool | None = None
    patch_successfully_applied: bool | None = None
    patch_is_none: bool | None = None
    log_path: str | None = None
    test_output_path: str | None = None
    failure_summary: str | None = None
    failure_excerpt: str | None = None

    @property
    def fail_to_pass_passed(self) -> list[str]:
        return _tests_status_list(self.tests_status, "FAIL_TO_PASS", "success")

    @property
    def fail_to_pass_failed(self) -> list[str]:
        return _tests_status_list(self.tests_status, "FAIL_TO_PASS", "failure")

    @property
    def pass_to_pass_passed(self) -> list[str]:
        return _tests_status_list(self.tests_status, "PASS_TO_PASS", "success")

    @property
    def pass_to_pass_failed(self) -> list[str]:
        return _tests_status_list(self.tests_status, "PASS_TO_PASS", "failure")

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "resolved": self.resolved,
            "status": self.status,
            "error": self.error,
            "patch_exists": self.patch_exists,
            "patch_successfully_applied": self.patch_successfully_applied,
            "patch_is_none": self.patch_is_none,
            "log_path": self.log_path,
            "test_output_path": self.test_output_path,
            "failure_summary": self.failure_summary,
            "failure_excerpt": self.failure_excerpt,
            "fail_to_pass_passed": list(self.fail_to_pass_passed),
            "fail_to_pass_failed": list(self.fail_to_pass_failed),
            "pass_to_pass_passed": list(self.pass_to_pass_passed),
            "pass_to_pass_failed": list(self.pass_to_pass_failed),
            "tests_status": dict(self.tests_status),
            "raw": dict(self.raw),
        }


def build_swebench_predictions_from_report(
    report: Mapping[str, Any],
    *,
    model_name_or_path: str,
    report_path: str | Path | None = None,
    include_empty_patches: bool = True,
    task_ids: list[str] | None = None,
    limit: int | None = None,
) -> list[SWEbenchPrediction]:
    """Build official SWE-bench predictions from a CodeAgent-X benchmark report."""

    wanted_task_ids = {str(item) for item in task_ids or []}
    if limit is not None and limit <= 0:
        raise ValueError("SWE-bench prediction limit must be greater than 0")
    tasks_by_id = {
        str(task.get("task_id")): task
        for task in _list(report.get("tasks"))
        if isinstance(task, Mapping) and task.get("task_id") is not None
    }
    predictions: list[SWEbenchPrediction] = []
    for raw_result in _list(report.get("results")):
        if not isinstance(raw_result, Mapping):
            continue
        task_id = raw_result.get("task_id")
        if task_id is None:
            continue
        task = tasks_by_id.get(str(task_id), {})
        if not _is_swebench_task(task):
            continue
        instance_id = _swebench_instance_id(task, str(task_id))
        if (
            wanted_task_ids
            and str(task_id) not in wanted_task_ids
            and instance_id not in wanted_task_ids
        ):
            continue
        patch = _patch_from_result(raw_result, report_path=report_path)
        if not patch.strip() and not include_empty_patches:
            continue
        predictions.append(
            SWEbenchPrediction(
                instance_id=instance_id,
                model_name_or_path=model_name_or_path,
                model_patch=patch,
            )
        )
        if limit is not None and len(predictions) >= limit:
            break
    if not predictions:
        raise ValueError("benchmark report contains no SWE-bench predictions")
    return predictions


def write_swebench_predictions_file(
    predictions: list[SWEbenchPrediction],
    output_path: str | Path,
    *,
    source_report_path: str | Path | None = None,
) -> SWEbenchPredictionsArtifact:
    """Write predictions as JSONL accepted by the official SWE-bench harness."""

    if not predictions:
        raise ValueError("cannot write an empty SWE-bench predictions file")
    output = Path(output_path).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(prediction.to_dict(), ensure_ascii=False)
        for prediction in predictions
    ]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")

    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    artifact = SWEbenchPredictionsArtifact(
        predictions_path=str(output),
        manifest_path=str(manifest_path),
        source_report_path=str(source_report_path) if source_report_path else None,
        model_name_or_path=predictions[0].model_name_or_path,
        prediction_count=len(predictions),
        patch_generated_count=sum(1 for prediction in predictions if prediction.patch_generated),
        empty_patch_count=sum(1 for prediction in predictions if not prediction.patch_generated),
        total_patch_bytes=sum(prediction.patch_bytes for prediction in predictions),
        instance_ids=[prediction.instance_id for prediction in predictions],
    )
    manifest_path.write_text(
        json.dumps(artifact.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return artifact


def write_swebench_predictions_from_report(
    report_path: str | Path,
    output_path: str | Path,
    *,
    model_name_or_path: str,
    include_empty_patches: bool = True,
    task_ids: list[str] | None = None,
    limit: int | None = None,
) -> SWEbenchPredictionsArtifact:
    """Read a benchmark report and write an official SWE-bench predictions JSONL."""

    path = Path(report_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("benchmark report JSON must be an object")
    predictions = build_swebench_predictions_from_report(
        payload,
        model_name_or_path=model_name_or_path,
        report_path=path,
        include_empty_patches=include_empty_patches,
        task_ids=task_ids,
        limit=limit,
    )
    return write_swebench_predictions_file(
        predictions,
        output_path,
        source_report_path=path,
    )


def run_swebench_evaluation(
    predictions_path: str | Path,
    *,
    config: SWEbenchEvaluatorConfig,
    instance_ids: list[str] | None = None,
    cwd: str | Path | None = None,
    process_timeout_seconds: int | None = None,
) -> SWEbenchEvaluationResult:
    """Invoke the official `swebench.harness.run_evaluation` command."""

    argv = config.to_argv(predictions_path, instance_ids=instance_ids)
    started = time.perf_counter()
    run_cwd = Path(cwd).expanduser() if cwd is not None else None
    try:
        completed = subprocess.run(
            argv,
            cwd=run_cwd,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=process_timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return SWEbenchEvaluationResult(
            command=argv,
            exit_code=None,
            stdout=_truncate(_coerce_text(exc.stdout)),
            stderr=_truncate(_coerce_text(exc.stderr)),
            duration_seconds=_elapsed(started),
            timed_out=True,
            predictions_path=str(predictions_path),
            run_id=config.run_id,
            results_path=_evaluation_results_path(config, run_cwd),
            instance_results_path=_evaluation_instance_results_path(config, run_cwd),
        )
    except OSError as exc:
        return SWEbenchEvaluationResult(
            command=argv,
            exit_code=None,
            stderr=f"{exc.__class__.__name__}: {exc}",
            duration_seconds=_elapsed(started),
            predictions_path=str(predictions_path),
            run_id=config.run_id,
            results_path=_evaluation_results_path(config, run_cwd),
            instance_results_path=_evaluation_instance_results_path(config, run_cwd),
        )

    results_path = _discover_evaluation_results_path(
        config,
        run_cwd,
        stdout=completed.stdout,
    )
    return SWEbenchEvaluationResult(
        command=argv,
        exit_code=completed.returncode,
        stdout=_truncate(completed.stdout),
        stderr=_truncate(completed.stderr),
        duration_seconds=_elapsed(started),
        predictions_path=str(predictions_path),
        run_id=config.run_id,
        results_path=results_path,
        instance_results_path=_evaluation_instance_results_path(config, run_cwd),
    )


def load_swebench_official_outcomes(
    results_path: str | Path,
) -> dict[str, SWEbenchOfficialOutcome]:
    """Load resolved statuses from an official SWE-bench result JSON/JSONL file."""

    path = Path(results_path)
    if not path.exists():
        raise FileNotFoundError(path)
    payload = _load_results_payload(path)
    outcomes = _extract_official_outcomes(payload)
    companion_outcomes = _load_companion_official_outcomes(
        path,
        instance_ids=set(outcomes),
    )
    for instance_id, outcome in companion_outcomes.items():
        outcomes[instance_id] = _merge_official_outcome(
            outcomes.get(instance_id),
            outcome,
        )
    companion_log_outcomes = _load_companion_official_log_outcomes(
        path,
        instance_ids=set(outcomes),
    )
    for instance_id, outcome in companion_log_outcomes.items():
        outcomes[instance_id] = _merge_official_outcome(
            outcomes.get(instance_id),
            outcome,
        )
    if not outcomes:
        raise ValueError(f"no SWE-bench official outcomes found in {path}")
    return outcomes


def annotate_benchmark_report_with_swebench_evaluation(
    report_path: str | Path,
    results_path: str | Path,
    output_path: str | Path | None = None,
) -> Path:
    """Write a benchmark report copy annotated with official SWE-bench results."""

    report_file = Path(report_path)
    payload = json.loads(report_file.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("benchmark report JSON must be an object")

    outcomes = load_swebench_official_outcomes(results_path)
    annotated = dict(payload)
    tasks = [
        dict(task)
        for task in _list(payload.get("tasks"))
        if isinstance(task, Mapping)
    ]
    swebench_task_ids = {
        str(task.get("task_id")): _swebench_instance_id(task, str(task.get("task_id")))
        for task in tasks
        if task.get("task_id") is not None and _is_swebench_task(task)
    }

    annotated_results: list[dict[str, Any]] = []
    for result in _list(payload.get("results")):
        if not isinstance(result, Mapping):
            continue
        item = dict(result)
        task_id = str(item.get("task_id"))
        instance_id = swebench_task_ids.get(task_id)
        outcome = outcomes.get(instance_id) if instance_id else None
        metrics = dict(item.get("metrics") or {})
        if outcome is not None:
            item["official_resolved"] = outcome.resolved
            item["official_status"] = outcome.status
            item["official_error"] = outcome.error
            if outcome.patch_exists is not None:
                item["official_patch_exists"] = outcome.patch_exists
            if outcome.patch_successfully_applied is not None:
                item["official_patch_successfully_applied"] = (
                    outcome.patch_successfully_applied
                )
            if outcome.patch_is_none is not None:
                item["official_patch_is_none"] = outcome.patch_is_none
            if outcome.log_path:
                item["official_log_path"] = outcome.log_path
            if outcome.test_output_path:
                item["official_test_output_path"] = outcome.test_output_path
            if outcome.failure_summary:
                item["official_failure_summary"] = outcome.failure_summary
            if outcome.failure_excerpt:
                item["official_failure_excerpt"] = outcome.failure_excerpt
            if outcome.tests_status:
                item["official_tests_status"] = outcome.tests_status
                item["official_fail_to_pass_passed"] = outcome.fail_to_pass_passed
                item["official_fail_to_pass_failed"] = outcome.fail_to_pass_failed
                item["official_pass_to_pass_passed"] = outcome.pass_to_pass_passed
                item["official_pass_to_pass_failed"] = outcome.pass_to_pass_failed
            metrics["swebench_official_resolved"] = outcome.resolved
            metrics["swebench_official_status"] = outcome.status
            metrics["swebench_official_fail_to_pass_failed_count"] = len(
                outcome.fail_to_pass_failed
            )
            metrics["swebench_official_pass_to_pass_failed_count"] = len(
                outcome.pass_to_pass_failed
            )
            if outcome.patch_successfully_applied is not None:
                metrics["swebench_official_patch_successfully_applied"] = (
                    outcome.patch_successfully_applied
                )
        item["metrics"] = metrics
        annotated_results.append(item)

    total = len(swebench_task_ids)
    resolved = sum(
        1
        for instance_id in swebench_task_ids.values()
        if outcomes.get(instance_id) and outcomes[instance_id].resolved is True
    )
    evaluated = sum(
        1
        for instance_id in swebench_task_ids.values()
        if instance_id in outcomes
    )
    error_tasks = sum(
        1
        for instance_id in swebench_task_ids.values()
        if (
            instance_id in outcomes
            and outcomes[instance_id].status.strip().lower() in ("error", "errored")
        )
    )
    annotated["results"] = annotated_results
    annotated["swebench_official_evaluation"] = {
        "schema_version": SWEBENCH_ANNOTATED_REPORT_SCHEMA_VERSION,
        "results_path": str(results_path),
        "total_tasks": total,
        "evaluated_tasks": evaluated,
        "resolved_tasks": resolved,
        "unresolved_tasks": evaluated - resolved,
        "non_error_unresolved_tasks": max(evaluated - resolved - error_tasks, 0),
        "error_tasks": error_tasks,
        "missing_tasks": total - evaluated,
        "resolved_rate": _ratio(resolved, total),
        "evaluated_resolved_rate": _ratio(resolved, evaluated),
        "outcomes": {
            instance_id: outcome.to_dict()
            for instance_id, outcome in sorted(outcomes.items())
        },
    }

    output = (
        Path(output_path)
        if output_path is not None
        else report_file.with_name("report.swebench.json")
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(annotated, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output


def _patch_from_result(
    result: Mapping[str, Any],
    *,
    report_path: str | Path | None,
) -> str:
    for artifact in _list(result.get("artifacts")):
        if not isinstance(artifact, Mapping) or artifact.get("kind") != "git_diff":
            continue
        patch_path = artifact.get("patch_path")
        if not patch_path:
            continue
        path = _resolve_report_path(str(patch_path), report_path)
        if path.exists() and path.is_file():
            return path.read_text(encoding="utf-8")
    return ""


def _resolve_report_path(raw_path: str, report_path: str | Path | None) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path
    if path.exists():
        return path
    if report_path is not None:
        report_dir = Path(report_path).expanduser().parent
        candidate = report_dir / path
        if candidate.exists():
            return candidate
    return path


def _is_swebench_task(task: Mapping[str, Any]) -> bool:
    metadata = task.get("metadata", {})
    return isinstance(metadata, Mapping) and isinstance(metadata.get("swebench"), Mapping)


def _swebench_instance_id(task: Mapping[str, Any], fallback: str) -> str:
    metadata = task.get("metadata", {})
    if isinstance(metadata, Mapping):
        swebench = metadata.get("swebench", {})
        if isinstance(swebench, Mapping) and swebench.get("instance_id"):
            return str(swebench["instance_id"])
    return fallback


def _evaluation_results_path(config: SWEbenchEvaluatorConfig, cwd: Path | None) -> str:
    return str(_evaluation_root(config, cwd) / "results.json")


def _evaluation_instance_results_path(config: SWEbenchEvaluatorConfig, cwd: Path | None) -> str:
    return str(_evaluation_root(config, cwd) / "instance_results.jsonl")


def _evaluation_root(config: SWEbenchEvaluatorConfig, cwd: Path | None) -> Path:
    root = cwd or Path.cwd()
    report_dir = Path(config.report_dir).expanduser() if config.report_dir else root
    return report_dir / "evaluation_results" / config.run_id


def _discover_evaluation_results_path(
    config: SWEbenchEvaluatorConfig,
    cwd: Path | None,
    *,
    stdout: str,
) -> str:
    expected = Path(_evaluation_results_path(config, cwd))
    if expected.exists():
        return str(expected)

    root = cwd or Path.cwd()
    for candidate in _stdout_report_candidates(stdout, root=root):
        if candidate.exists() and candidate.is_file():
            return str(candidate)
    return str(expected)


def _stdout_report_candidates(stdout: str, *, root: Path) -> list[Path]:
    candidates: list[Path] = []
    for match in re.finditer(r"Report written to\s+([^\r\n]+?\.json)\s*(?:\r?\n|$)", stdout):
        raw_path = match.group(1).strip().strip("\"'")
        if not raw_path:
            continue
        path = Path(raw_path).expanduser()
        candidates.append(path if path.is_absolute() else root / path)
    return candidates


def _load_companion_official_outcomes(
    results_path: Path,
    *,
    instance_ids: set[str],
) -> dict[str, SWEbenchOfficialOutcome]:
    """Load per-instance SWE-bench reports near an official summary file."""

    roots = _companion_log_roots(results_path)
    if not roots:
        return {}

    outcomes: dict[str, SWEbenchOfficialOutcome] = {}
    scanned = 0
    max_reports = 1000
    for root in roots:
        for report_path in root.rglob("report.json"):
            if report_path == results_path:
                continue
            scanned += 1
            if scanned > max_reports:
                return outcomes
            try:
                payload = _load_results_payload(report_path)
            except (OSError, json.JSONDecodeError):
                continue
            for instance_id, outcome in _extract_official_outcomes(payload).items():
                if instance_ids and instance_id not in instance_ids:
                    continue
                outcomes[instance_id] = _merge_official_outcome(
                    outcomes.get(instance_id),
                    _attach_companion_paths(outcome, report_path.parent),
                )
    return outcomes


def _companion_log_roots(results_path: Path) -> list[Path]:
    roots: list[Path] = []
    seen: set[Path] = set()
    for parent in (results_path.parent, *results_path.parents):
        candidate = parent / "logs" / "run_evaluation"
        for root in _scoped_companion_log_roots(results_path, candidate):
            try:
                resolved = root.resolve()
            except OSError:
                resolved = root
            if root.exists() and root.is_dir() and resolved not in seen:
                roots.append(root)
                seen.add(resolved)
        if roots:
            return roots

    for parent in (results_path.parent, *results_path.parents):
        candidate = parent / "logs" / "run_evaluation"
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        if candidate.exists() and candidate.is_dir() and resolved not in seen:
            roots.append(candidate)
            seen.add(resolved)
            return roots
    return roots


def _scoped_companion_log_roots(results_path: Path, run_evaluation_root: Path) -> list[Path]:
    stem = results_path.name
    for suffix in (".jsonl", ".json"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break

    roots: list[Path] = []
    parts = stem.split(".")
    for index in range(1, len(parts)):
        model_name = ".".join(parts[:index])
        run_id = ".".join(parts[index:])
        if not model_name or not run_id:
            continue
        roots.append(run_evaluation_root / run_id / model_name)
    return roots


def _load_companion_official_log_outcomes(
    results_path: Path,
    *,
    instance_ids: set[str],
) -> dict[str, SWEbenchOfficialOutcome]:
    """Load evaluator log/test-output evidence from per-instance log folders."""

    roots = _companion_log_roots(results_path)
    if not roots:
        return {}

    outcomes: dict[str, SWEbenchOfficialOutcome] = {}
    scanned = 0
    max_logs = 1000
    for root in roots:
        for log_path in root.rglob("run_instance.log"):
            scanned += 1
            if scanned > max_logs:
                return outcomes
            instance_id = log_path.parent.name
            if instance_ids and instance_id not in instance_ids:
                continue
            outcomes[instance_id] = _merge_official_outcome(
                outcomes.get(instance_id),
                _outcome_from_companion_paths(instance_id, log_path.parent),
            )
    return outcomes


def _attach_companion_paths(
    outcome: SWEbenchOfficialOutcome,
    companion_dir: Path,
) -> SWEbenchOfficialOutcome:
    path_outcome = _outcome_from_companion_paths(outcome.instance_id, companion_dir)
    return _merge_official_outcome(outcome, path_outcome)


def _outcome_from_companion_paths(
    instance_id: str,
    companion_dir: Path,
) -> SWEbenchOfficialOutcome:
    log_path = companion_dir / "run_instance.log"
    test_output_path = companion_dir / "test_output.txt"
    log_text = _read_optional_text(log_path)
    test_output_text = _read_optional_text(test_output_path)
    summary = _failure_summary_from_evaluator_output(
        log_text=log_text,
        test_output_text=test_output_text,
    )
    excerpt = _failure_excerpt_from_evaluator_output(
        log_text=log_text,
        test_output_text=test_output_text,
    )
    return SWEbenchOfficialOutcome(
        instance_id=instance_id,
        resolved=None,
        status="unknown",
        log_path=str(log_path) if log_path.exists() else None,
        test_output_path=str(test_output_path) if test_output_path.exists() else None,
        failure_summary=summary,
        failure_excerpt=excerpt,
    )


def _read_optional_text(path: Path, *, max_chars: int = 120_000) -> str:
    if not path.exists() or not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _failure_summary_from_evaluator_output(
    *,
    log_text: str,
    test_output_text: str,
) -> str | None:
    clean_log = _strip_ansi(log_text)
    clean_tests = _strip_ansi(test_output_text)
    patch_failure = _first_matching_line(
        clean_log,
        (
            "Patch Apply Failed",
            "Hunk #",
            "Failed to apply patch",
        ),
    )
    if patch_failure:
        return patch_failure
    failed_test = _first_matching_line(clean_tests, ("FAILED ", "E   ", "E       "))
    if failed_test:
        return failed_test
    result_line = _first_matching_line(clean_log, ("Result for ", "report: "))
    if result_line:
        return result_line
    return None


def _failure_excerpt_from_evaluator_output(
    *,
    log_text: str,
    test_output_text: str,
) -> str | None:
    clean_log = _strip_ansi(log_text)
    clean_tests = _strip_ansi(test_output_text)
    excerpt = _excerpt_around_markers(
        clean_log,
        ("Patch Apply Failed", "Hunk #", "Failed to apply patch"),
        before=2,
        after=5,
    )
    if excerpt:
        return excerpt
    excerpt = _excerpt_around_markers(
        clean_tests,
        ("FAILURES", "FAILED ", "E   ", "E       "),
        before=2,
        after=8,
    )
    if excerpt:
        return excerpt
    return None


def _first_matching_line(text: str, markers: tuple[str, ...]) -> str | None:
    for line in text.splitlines():
        cleaned = _clean_evaluator_line(line)
        if not cleaned:
            continue
        if any(marker in cleaned for marker in markers):
            return _truncate_line(cleaned)
    return None


def _excerpt_around_markers(
    text: str,
    markers: tuple[str, ...],
    *,
    before: int,
    after: int,
) -> str | None:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        cleaned = _clean_evaluator_line(line)
        if any(marker in cleaned for marker in markers):
            start = max(index - before, 0)
            end = min(index + after + 1, len(lines))
            excerpt_lines = [
                _truncate_line(_clean_evaluator_line(item))
                for item in lines[start:end]
                if _clean_evaluator_line(item)
            ]
            if excerpt_lines:
                return "\n".join(excerpt_lines)
    return None


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _clean_evaluator_line(line: str) -> str:
    text = line.strip()
    text = re.sub(r"^\d{4}-\d{2}-\d{2} [0-9:,]+ - [A-Z]+ -\s*", "", text)
    return text


def _truncate_line(line: str, *, limit: int = 240) -> str:
    if len(line) <= limit:
        return line
    return line[: limit - 3].rstrip() + "..."


def _load_results_payload(path: Path) -> Any:
    if path.suffix.lower() == ".jsonl":
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_official_outcomes(payload: Any) -> dict[str, SWEbenchOfficialOutcome]:
    outcomes: dict[str, SWEbenchOfficialOutcome] = {}
    if isinstance(payload, list):
        for item in payload:
            _add_mapping_outcome(outcomes, item)
        return outcomes
    if not isinstance(payload, Mapping):
        return outcomes

    for instance_id in _string_list(payload.get("resolved_ids")):
        outcomes[instance_id] = SWEbenchOfficialOutcome(
            instance_id=instance_id,
            resolved=True,
            status="resolved",
        )
    for key in ("unresolved_ids", "failed_ids"):
        for instance_id in _string_list(payload.get(key)):
            outcomes[instance_id] = SWEbenchOfficialOutcome(
                instance_id=instance_id,
                resolved=False,
                status="unresolved",
            )
    for instance_id in _string_list(payload.get("error_ids")):
        outcomes[instance_id] = SWEbenchOfficialOutcome(
            instance_id=instance_id,
            resolved=False,
            status="error",
        )

    for key in ("instance_results", "results", "instances"):
        value = payload.get(key)
        if isinstance(value, list):
            for item in value:
                _add_mapping_outcome(outcomes, item)
        elif isinstance(value, Mapping):
            _add_mapping_outcomes(outcomes, value)

    _add_mapping_outcome(outcomes, payload)
    _add_mapping_outcomes(outcomes, payload)
    return outcomes


def _add_mapping_outcomes(
    outcomes: dict[str, SWEbenchOfficialOutcome],
    value: Mapping[str, Any],
) -> None:
    for instance_id, item in value.items():
        if not isinstance(item, Mapping):
            continue
        candidate = dict(item)
        candidate.setdefault("instance_id", instance_id)
        _add_mapping_outcome(outcomes, candidate)


def _add_mapping_outcome(
    outcomes: dict[str, SWEbenchOfficialOutcome],
    value: Any,
) -> None:
    if not isinstance(value, Mapping):
        return
    instance_id = _first_string(
        value,
        ("instance_id", "id", "task_id"),
    )
    if not instance_id:
        return
    resolved = _coerce_resolved(value)
    if resolved is None and "resolved" not in value and "status" not in value:
        return
    status = _official_status(value, resolved)
    outcomes[instance_id] = SWEbenchOfficialOutcome(
        instance_id=instance_id,
        resolved=resolved,
        status=status,
        error=_first_string(value, ("error", "error_msg", "message")),
        raw=dict(value),
        tests_status=_tests_status(value.get("tests_status")),
        patch_exists=_optional_bool(value.get("patch_exists")),
        patch_successfully_applied=_optional_bool(
            value.get("patch_successfully_applied")
        ),
        patch_is_none=_optional_bool(value.get("patch_is_None", value.get("patch_is_none"))),
        log_path=_first_string(value, ("log_path", "official_log_path")),
        test_output_path=_first_string(
            value,
            ("test_output_path", "official_test_output_path"),
        ),
        failure_summary=_first_string(
            value,
            ("failure_summary", "official_failure_summary"),
        ),
        failure_excerpt=_first_string(
            value,
            ("failure_excerpt", "official_failure_excerpt"),
        ),
    )


def _merge_official_outcome(
    existing: SWEbenchOfficialOutcome | None,
    incoming: SWEbenchOfficialOutcome,
) -> SWEbenchOfficialOutcome:
    if existing is None:
        return incoming
    raw = dict(existing.raw)
    raw.update(incoming.raw)
    return SWEbenchOfficialOutcome(
        instance_id=existing.instance_id,
        resolved=(
            incoming.resolved
            if incoming.resolved is not None
            else existing.resolved
        ),
        status=(
            incoming.status
            if incoming.status and incoming.status != "unknown"
            else existing.status
        ),
        error=incoming.error or existing.error,
        raw=raw,
        tests_status=incoming.tests_status or existing.tests_status,
        patch_exists=(
            incoming.patch_exists
            if incoming.patch_exists is not None
            else existing.patch_exists
        ),
        patch_successfully_applied=(
            incoming.patch_successfully_applied
            if incoming.patch_successfully_applied is not None
            else existing.patch_successfully_applied
        ),
        patch_is_none=(
            incoming.patch_is_none
            if incoming.patch_is_none is not None
            else existing.patch_is_none
        ),
        log_path=incoming.log_path or existing.log_path,
        test_output_path=incoming.test_output_path or existing.test_output_path,
        failure_summary=incoming.failure_summary or existing.failure_summary,
        failure_excerpt=incoming.failure_excerpt or existing.failure_excerpt,
    )


def _coerce_resolved(value: Mapping[str, Any]) -> bool | None:
    for key in ("resolved", "success", "passed"):
        if key in value:
            return _optional_bool(value.get(key))
    status = str(value.get("status", "")).strip().lower()
    if status in ("resolved", "pass", "passed", "success", "succeeded"):
        return True
    if status in ("unresolved", "fail", "failed", "error", "errored"):
        return False
    return None


def _official_status(value: Mapping[str, Any], resolved: bool | None) -> str:
    status = value.get("status")
    if status not in (None, ""):
        return str(status)
    if resolved is True:
        return "resolved"
    if resolved is False:
        return "unresolved"
    return "unknown"


def _first_string(value: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        item = value.get(key)
        if item not in (None, ""):
            return str(item)
    return None


def _tests_status(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    status: dict[str, Any] = {}
    for bucket, bucket_value in value.items():
        if isinstance(bucket_value, Mapping):
            status[str(bucket)] = {
                str(key): _string_list(item)
                if isinstance(item, (list, tuple, str))
                else item
                for key, item in bucket_value.items()
            }
        else:
            status[str(bucket)] = bucket_value
    return status


def _tests_status_list(
    tests_status: Mapping[str, Any],
    bucket: str,
    key: str,
) -> list[str]:
    bucket_value = tests_status.get(bucket)
    if not isinstance(bucket_value, Mapping):
        return []
    return _string_list(bucket_value.get(key))


def _string_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple):
        return [str(item) for item in value]
    return []


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in ("1", "true", "yes", "y", "on"):
        return True
    if normalized in ("0", "false", "no", "n", "off"):
        return False
    return None


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 6)


def _bool_arg(value: bool) -> str:
    return "true" if value else "false"


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _coerce_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _truncate(value: object, max_chars: int = MAX_EVALUATOR_OUTPUT_CHARS) -> str:
    text = _coerce_text(value)
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return text[:max_chars] + f"\n... output truncated {omitted} chars"


def _elapsed(started: float) -> float:
    return round(time.perf_counter() - started, 6)
