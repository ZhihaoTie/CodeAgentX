"""Tests for the benchmark harness."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from codeagentx.config import Config, PermissionMode
from codeagentx.evaluation import (
    BENCHMARK_ABLATION_SCHEMA_VERSION,
    BENCHMARK_SCHEMA_VERSION,
    BenchmarkAblationRunner,
    BenchmarkAblationVariant,
    BenchmarkReport,
    BenchmarkRunner,
    BenchmarkTaskResult,
    BenchmarkTaskSpec,
    load_benchmark_ablation_spec,
    load_benchmark_spec,
)
from codeagentx.models import MockProvider, ModelResponse


def python_command(code: str) -> str:
    return f'"{sys.executable}" -c "{code}"'


class TestBenchmarkSpec(unittest.TestCase):
    def test_loads_tasks_with_defaults_and_relative_workspace(self):
        with tempfile.TemporaryDirectory() as tempdir:
            spec_path = Path(tempdir) / "benchmark.json"
            spec_path.write_text(
                json.dumps({
                    "defaults": {
                        "workspace_root": ".",
                        "permission_mode": "auto",
                        "enable_runtime_planning": True,
                        "enable_context_ranking": True,
                        "context_ranking_limit": 5,
                        "enable_long_term_memory": True,
                        "memory_store_path": "memory.jsonl",
                        "memory_retrieval_limit": 2,
                        "memory_min_score": 24,
                        "memory_prompt_max_chars": 1200,
                        "enable_task_constraints": True,
                        "success_criteria": ["Tests pass"],
                        "required_changed_paths": ["src/*.py"],
                        "forbidden_changed_paths": ["docs/*"],
                        "required_final_response_substrings": ["Done"],
                        "forbidden_final_response_substrings": ["failed"],
                        "auto_rollback_on_verification_failure": True,
                        "enable_patch_policy": True,
                        "patch_policy_max_changed_files": 10,
                        "patch_policy_max_total_changed_lines": 500,
                        "enable_failure_reflection": True,
                        "max_reflection_retries": 1,
                        "enable_retry_strategy_matrix": True,
                        "enable_tool_planning_guidance": True,
                        "enable_git_diff_artifact": True,
                        "git_diff_base_ref": "HEAD",
                        "max_tool_calls": 9,
                        "max_run_seconds": 12.5,
                        "verification_sandbox": "local",
                        "enable_sandbox_artifacts": True,
                        "sandbox_snapshot_max_files": 123,
                        "sandbox_snapshot_max_recorded_files": 12,
                        "docker_sandbox_image": "python:3.12",
                        "docker_sandbox_network": "none",
                        "docker_sandbox_memory": "512m",
                        "docker_sandbox_cpus": "1.0",
                        "tags": ["smoke"],
                    },
                    "tasks": [{
                        "id": "demo-task",
                        "goal": "verify demo",
                        "verification_command": python_command("print('ok')"),
                    }],
                }),
                encoding="utf-8",
            )

            tasks = load_benchmark_spec(spec_path)

        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].task_id, "demo-task")
        self.assertEqual(tasks[0].workspace_root, str(Path(tempdir).resolve()))
        self.assertEqual(tasks[0].permission_mode, PermissionMode.AUTO)
        self.assertTrue(tasks[0].enable_runtime_planning)
        self.assertTrue(tasks[0].enable_context_ranking)
        self.assertEqual(tasks[0].context_ranking_limit, 5)
        self.assertTrue(tasks[0].enable_long_term_memory)
        self.assertEqual(tasks[0].memory_store_path, "memory.jsonl")
        self.assertEqual(tasks[0].memory_retrieval_limit, 2)
        self.assertEqual(tasks[0].memory_min_score, 24)
        self.assertEqual(tasks[0].memory_prompt_max_chars, 1200)
        self.assertTrue(tasks[0].enable_task_constraints)
        self.assertEqual(tasks[0].success_criteria, ["Tests pass"])
        self.assertEqual(tasks[0].required_changed_paths, ["src/*.py"])
        self.assertEqual(tasks[0].forbidden_changed_paths, ["docs/*"])
        self.assertEqual(tasks[0].required_final_response_substrings, ["Done"])
        self.assertEqual(tasks[0].forbidden_final_response_substrings, ["failed"])
        self.assertTrue(tasks[0].auto_rollback_on_verification_failure)
        self.assertTrue(tasks[0].enable_patch_policy)
        self.assertEqual(tasks[0].patch_policy_max_changed_files, 10)
        self.assertEqual(tasks[0].patch_policy_max_total_changed_lines, 500)
        self.assertTrue(tasks[0].enable_failure_reflection)
        self.assertEqual(tasks[0].max_reflection_retries, 1)
        self.assertTrue(tasks[0].enable_retry_strategy_matrix)
        self.assertTrue(tasks[0].enable_tool_planning_guidance)
        self.assertTrue(tasks[0].enable_git_diff_artifact)
        self.assertEqual(tasks[0].git_diff_base_ref, "HEAD")
        self.assertEqual(tasks[0].max_tool_calls, 9)
        self.assertEqual(tasks[0].max_run_seconds, 12.5)
        self.assertEqual(tasks[0].verification_sandbox, "local")
        self.assertTrue(tasks[0].enable_sandbox_artifacts)
        self.assertEqual(tasks[0].sandbox_snapshot_max_files, 123)
        self.assertEqual(tasks[0].sandbox_snapshot_max_recorded_files, 12)
        self.assertEqual(tasks[0].docker_sandbox_image, "python:3.12")
        self.assertEqual(tasks[0].docker_sandbox_network, "none")
        self.assertEqual(tasks[0].docker_sandbox_memory, "512m")
        self.assertEqual(tasks[0].docker_sandbox_cpus, "1.0")
        self.assertEqual(tasks[0].tags, ["smoke"])

    def test_loads_ablation_variants_from_spec(self):
        with tempfile.TemporaryDirectory() as tempdir:
            spec_path = Path(tempdir) / "benchmark.json"
            spec_path.write_text(
                json.dumps({
                    "defaults": {
                        "workspace_root": ".",
                        "permission_mode": "auto",
                    },
                    "ablation_variants": [
                        {"name": "baseline", "overrides": {}},
                        {
                            "name": "no_context_ranking",
                            "description": "Disable ranking.",
                            "overrides": {"enable_context_ranking": False},
                        },
                    ],
                    "tasks": [{
                        "id": "demo-task",
                        "goal": "verify demo",
                        "verification_command": python_command("print('ok')"),
                    }],
                }),
                encoding="utf-8",
            )

            tasks, variants = load_benchmark_ablation_spec(spec_path)

        self.assertEqual([task.task_id for task in tasks], ["demo-task"])
        self.assertEqual([variant.name for variant in variants], [
            "baseline",
            "no_context_ranking",
        ])
        self.assertEqual(
            variants[1].overrides,
            {"enable_context_ranking": False},
        )


class TestBenchmarkRunner(unittest.TestCase):
    def test_runs_task_and_writes_report(self):
        with tempfile.TemporaryDirectory() as tempdir:
            output_dir = Path(tempdir) / "benchmarks"
            spec = BenchmarkTaskSpec(
                task_id="unittest-pass",
                goal="run verification",
                workspace_root=tempdir,
                verification_command=python_command(
                    "import sys; "
                    "sys.stderr.write('Ran 2 tests in 0.001s\\n\\nOK\\n')"
                ),
                permission_mode=PermissionMode.AUTO,
            )
            runner = BenchmarkRunner(
                base_config=Config(
                    model_provider="mock",
                    model="mock-model",
                    trajectory_dir=None,
                    permission_mode=PermissionMode.AUTO,
                ),
                provider_factory=lambda task: MockProvider([
                    ModelResponse.text("Done.", model="mock-model")
                ]),
                output_dir=output_dir,
            )

            report = runner.run([spec], run_id="run-1")
            report_payload = json.loads(Path(report.report_path).read_text(encoding="utf-8"))
            result = report.results[0]
            state_path_exists = Path(result.state_path).exists()
            events_path_exists = Path(result.events_path).exists()
            artifact_count = len(result.artifacts)
            artifact_path_exists = Path(result.artifacts[0]["result_path"]).exists()
            artifact_payload = json.loads(
                Path(result.artifacts[0]["result_path"]).read_text(encoding="utf-8")
            )

        self.assertEqual(report_payload["schema_version"], BENCHMARK_SCHEMA_VERSION)
        self.assertEqual(report_payload["memory_policy"]["policy"], "shared")
        self.assertTrue(report_payload["memory_policy"]["cross_task_reuse"])
        self.assertEqual(report.total_tasks, 1)
        self.assertEqual(report.resolved_tasks, 1)
        self.assertEqual(report.resolved_rate, 1.0)
        self.assertEqual(report_payload["summary"]["artifact_count"], 1)
        self.assertEqual(report_payload["summary"]["first_pass_success_tasks"], 1)
        self.assertEqual(report_payload["summary"]["first_pass_success_rate"], 1.0)
        self.assertEqual(report_payload["summary"]["retry_attempted_tasks"], 0)
        self.assertEqual(report_payload["summary"]["retry_recovered_tasks"], 0)
        self.assertEqual(report_payload["summary"]["retry_recovery_rate"], 0.0)
        self.assertEqual(report_payload["summary"]["average_budget_turns"], 1.0)
        self.assertEqual(report_payload["summary"]["average_budget_tool_calls"], 0.0)
        self.assertEqual(report_payload["summary"]["average_budget_total_tokens"], 0.0)
        self.assertEqual(report_payload["summary"]["budget_exhausted_tasks"], 0)
        self.assertEqual(report_payload["summary"]["average_patch_changed_files"], 0.0)
        self.assertEqual(report_payload["summary"]["average_patch_changed_lines"], 0.0)
        self.assertTrue(result.resolved)
        self.assertEqual(result.verification_status, "passed")
        self.assertEqual(result.metrics["structured_tests_total"], 2)
        self.assertEqual(result.metrics["structured_tests_passed"], 2)
        self.assertEqual(result.metrics["budget_turns"], 1)
        self.assertEqual(result.metrics["budget_tool_calls"], 0)
        self.assertFalse(result.metrics["budget_exhausted"])
        self.assertEqual(result.metrics["verification_sandbox_type"], "local")
        self.assertEqual(result.metrics["verification_sandbox_status"], "passed")
        self.assertEqual(result.metrics["verification_artifact_count"], 1)
        self.assertIsNotNone(result.metrics["verification_workspace_sha256"])
        self.assertEqual(artifact_count, 1)
        self.assertTrue(artifact_path_exists)
        self.assertEqual(Path(result.artifacts[0]["artifact_dir"]).parts[-2], "unittest-pass")
        self.assertEqual(artifact_payload["kind"], "verification")
        self.assertTrue(state_path_exists)
        self.assertTrue(events_path_exists)

    def test_memory_policy_isolates_task_memory_stores(self):
        with tempfile.TemporaryDirectory() as tempdir:
            workspace = Path(tempdir) / "workspace"
            workspace.mkdir()
            output_dir = Path(tempdir) / "benchmarks"
            specs = [
                BenchmarkTaskSpec(
                    task_id="task-a",
                    goal="finish alpha",
                    workspace_root=str(workspace),
                    verification_command=python_command("print('tests pass')"),
                    permission_mode=PermissionMode.AUTO,
                    enable_long_term_memory=True,
                ),
                BenchmarkTaskSpec(
                    task_id="task-b",
                    goal="finish beta",
                    workspace_root=str(workspace),
                    verification_command=python_command("print('tests pass')"),
                    permission_mode=PermissionMode.AUTO,
                    enable_long_term_memory=True,
                ),
            ]
            runner = BenchmarkRunner(
                base_config=Config(
                    model_provider="mock",
                    model="mock-model",
                    permission_mode=PermissionMode.AUTO,
                    enable_long_term_memory=True,
                    enable_sandbox_artifacts=False,
                ),
                provider_factory=lambda task: MockProvider([
                    ModelResponse.text("Done.", model="mock-model")
                ]),
                output_dir=output_dir,
                memory_policy="isolated",
            )

            report = runner.run(specs, run_id="run-isolated-memory")
            payload = json.loads(Path(report.report_path).read_text(encoding="utf-8"))
            memory_a = output_dir / "run-isolated-memory" / "memory" / "task-a" / "memories.jsonl"
            memory_b = output_dir / "run-isolated-memory" / "memory" / "task-b" / "memories.jsonl"
            shared_memory = output_dir / "run-isolated-memory" / "memory" / "memories.jsonl"
            memory_a_exists = memory_a.exists()
            memory_b_exists = memory_b.exists()
            shared_memory_exists = shared_memory.exists()
            memory_a_lines = memory_a.read_text(encoding="utf-8").splitlines()
            memory_b_lines = memory_b.read_text(encoding="utf-8").splitlines()

        self.assertEqual(payload["memory_policy"]["policy"], "isolated")
        self.assertFalse(payload["memory_policy"]["cross_task_reuse"])
        self.assertEqual(payload["memory_policy"]["store_scope"], "task")
        self.assertEqual(payload["memory_policy"]["memory_enabled_task_count"], 2)
        self.assertTrue(memory_a_exists)
        self.assertTrue(memory_b_exists)
        self.assertFalse(shared_memory_exists)
        self.assertEqual(len(memory_a_lines), 1)
        self.assertEqual(len(memory_b_lines), 1)

    def test_memory_policy_disabled_forces_memory_off(self):
        with tempfile.TemporaryDirectory() as tempdir:
            workspace = Path(tempdir) / "workspace"
            workspace.mkdir()
            output_dir = Path(tempdir) / "benchmarks"
            spec = BenchmarkTaskSpec(
                task_id="task-disabled",
                goal="finish",
                workspace_root=str(workspace),
                verification_command=python_command("print('tests pass')"),
                permission_mode=PermissionMode.AUTO,
                enable_long_term_memory=True,
            )
            runner = BenchmarkRunner(
                base_config=Config(
                    model_provider="mock",
                    model="mock-model",
                    permission_mode=PermissionMode.AUTO,
                    enable_long_term_memory=True,
                    enable_sandbox_artifacts=False,
                ),
                provider_factory=lambda task: MockProvider([
                    ModelResponse.text("Done.", model="mock-model")
                ]),
                output_dir=output_dir,
                memory_policy="disabled",
            )

            report = runner.run([spec], run_id="run-memory-disabled")
            payload = json.loads(Path(report.report_path).read_text(encoding="utf-8"))
            result = report.results[0]
            memory_dir_exists = (output_dir / "run-memory-disabled" / "memory").exists()

        self.assertTrue(result.resolved)
        self.assertEqual(payload["memory_policy"]["policy"], "disabled")
        self.assertEqual(payload["memory_policy"]["store_scope"], "none")
        self.assertEqual(payload["memory_policy"]["memory_enabled_task_count"], 0)
        self.assertEqual(result.metrics["memory_retrieval_count"], 0)
        self.assertEqual(result.metrics["memory_extraction_count"], 0)
        self.assertFalse(memory_dir_exists)

    def test_runs_task_in_isolated_workspace_copy(self):
        with tempfile.TemporaryDirectory() as tempdir:
            source_workspace = Path(tempdir) / "fixture"
            source_workspace.mkdir()
            (source_workspace / "app.py").write_text("broken", encoding="utf-8")
            output_dir = Path(tempdir) / "benchmarks"
            spec = BenchmarkTaskSpec(
                task_id="isolated-edit",
                goal="fix app.py",
                workspace_root=str(source_workspace),
                verification_command=python_command(
                    "import pathlib, sys; "
                    "sys.exit(0 if pathlib.Path('app.py').read_text() == 'fixed' else 1)"
                ),
                permission_mode=PermissionMode.AUTO,
            )
            runner = BenchmarkRunner(
                base_config=Config(
                    model_provider="mock",
                    model="mock-model",
                    permission_mode=PermissionMode.AUTO,
                    enable_sandbox_artifacts=False,
                ),
                provider_factory=lambda task: MockProvider([
                    ModelResponse.tool_use(
                        tool_use_id="toolu_1",
                        name="write_file",
                        tool_input={"path": "app.py", "content": "fixed"},
                        text="I will fix app.py.",
                        model="mock-model",
                    ),
                    ModelResponse.text("Done.", model="mock-model"),
                ]),
                output_dir=output_dir,
            )

            report = runner.run([spec], run_id="run-isolated")
            result = report.results[0]
            run_workspace = Path(result.run_workspace_root)

            self.assertTrue(result.resolved)
            self.assertEqual((source_workspace / "app.py").read_text(encoding="utf-8"), "broken")
            self.assertEqual((run_workspace / "app.py").read_text(encoding="utf-8"), "fixed")
            self.assertEqual(result.original_workspace_root, str(source_workspace.resolve()))
            self.assertTrue(run_workspace.is_absolute())
            self.assertEqual(run_workspace.name, "isolated-edit")
            self.assertEqual(run_workspace.parent.name, "workspaces")

    @unittest.skipUnless(shutil.which("git"), "git executable is required")
    def test_writes_git_diff_artifact_for_enabled_task(self):
        with tempfile.TemporaryDirectory() as tempdir:
            source_workspace = Path(tempdir) / "fixture"
            source_workspace.mkdir()
            _git(source_workspace, "init")
            _git(source_workspace, "config", "user.email", "tester@example.com")
            _git(source_workspace, "config", "user.name", "Tester")
            (source_workspace / "app.py").write_text("broken\n", encoding="utf-8")
            _git(source_workspace, "add", ".")
            _git(source_workspace, "commit", "-m", "initial")

            output_dir = Path(tempdir) / "benchmarks"
            spec = BenchmarkTaskSpec(
                task_id="git-diff-task",
                goal="fix app.py",
                workspace_root=str(source_workspace),
                verification_command=python_command(
                    "import pathlib, sys; "
                    "sys.exit(0 if pathlib.Path('app.py').read_text() == 'fixed\\n' else 1)"
                ),
                permission_mode=PermissionMode.AUTO,
                enable_sandbox_artifacts=False,
                enable_git_diff_artifact=True,
                git_diff_base_ref="HEAD",
            )
            runner = BenchmarkRunner(
                base_config=Config(
                    model_provider="mock",
                    model="mock-model",
                    permission_mode=PermissionMode.AUTO,
                    enable_sandbox_artifacts=False,
                ),
                provider_factory=lambda task: MockProvider([
                    ModelResponse.tool_use(
                        tool_use_id="toolu_1",
                        name="write_file",
                        tool_input={"path": "app.py", "content": "fixed\n"},
                        text="I will fix app.py.",
                        model="mock-model",
                    ),
                    ModelResponse.text("Done.", model="mock-model"),
                ]),
                output_dir=output_dir,
            )

            report = runner.run([spec], run_id="run-git-diff")
            result = report.results[0]
            artifact = result.artifacts[0]
            patch_path = Path(artifact["patch_path"])
            patch_path_exists = patch_path.exists()
            patch_text = patch_path.read_text(encoding="utf-8")
            git_diff_payload = json.loads(
                Path(artifact["result_path"]).read_text(encoding="utf-8")
            )
            source_text = (source_workspace / "app.py").read_text(encoding="utf-8")
            run_workspace_git_exists = (Path(result.run_workspace_root) / ".git").exists()

        self.assertTrue(result.resolved)
        self.assertEqual(source_text, "broken\n")
        self.assertEqual(len(result.artifacts), 1)
        self.assertEqual(artifact["kind"], "git_diff")
        self.assertTrue(run_workspace_git_exists)
        self.assertTrue(patch_path_exists)
        self.assertIn("-broken", patch_text)
        self.assertIn("+fixed", patch_text)
        self.assertEqual(artifact["changed_files"], ["app.py"])
        self.assertGreater(artifact["patch_bytes"], 0)
        self.assertEqual(git_diff_payload["changed_files"], ["app.py"])
        self.assertEqual(result.metrics["git_diff_changed_files"], 1)
        self.assertGreater(result.metrics["git_diff_patch_bytes"], 0)
        self.assertTrue(result.metrics["git_diff_is_git_repository"])
        self.assertFalse(result.metrics["git_diff_is_clean"])
        self.assertIsNone(result.metrics["git_diff_error"])

    @unittest.skipUnless(shutil.which("git"), "git executable is required")
    def test_git_diff_forbidden_paths_fail_result_even_when_verification_passes(self):
        with tempfile.TemporaryDirectory() as tempdir:
            source_workspace = Path(tempdir) / "fixture"
            source_workspace.mkdir()
            _git(source_workspace, "init")
            _git(source_workspace, "config", "user.email", "tester@example.com")
            _git(source_workspace, "config", "user.name", "Tester")
            (source_workspace / "app.py").write_text("ok\n", encoding="utf-8")
            _git(source_workspace, "add", ".")
            _git(source_workspace, "commit", "-m", "initial")

            output_dir = Path(tempdir) / "benchmarks"
            spec = BenchmarkTaskSpec(
                task_id="dirty-git-diff",
                goal="leave a scratch file",
                workspace_root=str(source_workspace),
                verification_command=python_command("print('tests pass')"),
                permission_mode=PermissionMode.AUTO,
                enable_sandbox_artifacts=False,
                enable_git_diff_artifact=True,
                git_diff_base_ref="HEAD",
                forbidden_changed_paths=["test_fix.py"],
            )
            runner = BenchmarkRunner(
                base_config=Config(
                    model_provider="mock",
                    model="mock-model",
                    permission_mode=PermissionMode.AUTO,
                    enable_sandbox_artifacts=False,
                ),
                provider_factory=lambda task: MockProvider([
                    ModelResponse.tool_use(
                        tool_use_id="toolu_1",
                        name="bash",
                        tool_input={
                            "command": python_command(
                                "open('test_fix.py', 'w').write('scratch\\n')"
                            ),
                        },
                        text="I will create a temporary script.",
                        model="mock-model",
                    ),
                    ModelResponse.text("Done.", model="mock-model"),
                ]),
                output_dir=output_dir,
            )

            report = runner.run([spec], run_id="run-dirty-git-diff")
            result = report.results[0]
            artifact = result.artifacts[0]
            patch_text = Path(artifact["patch_path"]).read_text(encoding="utf-8")

        self.assertFalse(result.resolved)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.verification_status, "passed")
        self.assertEqual(result.metrics["git_diff_forbidden_path_count"], 1)
        self.assertEqual(result.metrics["git_diff_forbidden_paths"], ["test_fix.py"])
        self.assertEqual(result.metrics["git_diff_policy_status"], "failed")
        self.assertIn("test_fix.py", artifact["changed_files"])
        self.assertIn("diff --git a/test_fix.py b/test_fix.py", patch_text)
        self.assertEqual(report.summary()["average_git_diff_forbidden_paths"], 1.0)

    def test_final_config_overrides_win_over_task_defaults(self):
        with tempfile.TemporaryDirectory() as tempdir:
            spec = BenchmarkTaskSpec(
                task_id="no-artifacts",
                goal="finish",
                workspace_root=tempdir,
                verification_command=python_command("print('tests pass')"),
                permission_mode=PermissionMode.AUTO,
                enable_sandbox_artifacts=True,
            )
            runner = BenchmarkRunner(
                base_config=Config(
                    model_provider="mock",
                    model="mock-model",
                    permission_mode=PermissionMode.AUTO,
                    enable_sandbox_artifacts=True,
                ),
                provider_factory=lambda task: MockProvider([
                    ModelResponse.text("Done.", model="mock-model")
                ]),
                output_dir=Path(tempdir) / "benchmarks",
                final_config_overrides={
                    "enable_sandbox_artifacts": False,
                    "sandbox_artifact_dir": None,
                },
            )

            report = runner.run([spec], run_id="run-no-artifacts")

        result = report.results[0]
        self.assertTrue(result.resolved)
        self.assertEqual(result.artifacts, [])
        self.assertEqual(result.metrics["verification_artifact_count"], 0)

    def test_setup_failure_skips_agent_run(self):
        provider_calls: list[str] = []

        def provider_factory(task: BenchmarkTaskSpec) -> MockProvider:
            provider_calls.append(task.task_id)
            return MockProvider([ModelResponse.text("Done.", model="mock-model")])

        with tempfile.TemporaryDirectory() as tempdir:
            spec = BenchmarkTaskSpec(
                task_id="setup-fails",
                goal="should not run",
                workspace_root=tempdir,
                setup_command=python_command("import sys; sys.exit(7)"),
            )
            runner = BenchmarkRunner(
                base_config=Config(model_provider="mock"),
                provider_factory=provider_factory,
                output_dir=Path(tempdir) / "benchmarks",
            )

            report = runner.run([spec], run_id="run-setup-failure")

        result = report.results[0]
        self.assertEqual(provider_calls, [])
        self.assertFalse(result.resolved)
        self.assertEqual(result.status, "setup_failed")
        self.assertIsNotNone(result.setup_result)
        assert result.setup_result is not None
        self.assertEqual(result.setup_result.exit_code, 7)
        self.assertEqual(result.setup_result.sandbox["sandbox_type"], "local")
        self.assertEqual(result.setup_result.sandbox["status"], "failed")
        self.assertEqual(len(result.artifacts), 1)
        self.assertEqual(result.artifacts[0]["kind"], "setup")

    def test_patch_policy_failure_is_not_resolved_even_when_verification_passes(self):
        with tempfile.TemporaryDirectory() as tempdir:
            spec = BenchmarkTaskSpec(
                task_id="policy-fails",
                goal="write forbidden file",
                workspace_root=tempdir,
                verification_command=python_command("print('tests pass')"),
                permission_mode=PermissionMode.AUTO,
            )
            runner = BenchmarkRunner(
                base_config=Config(
                    model_provider="mock",
                    model="mock-model",
                    permission_mode=PermissionMode.AUTO,
                ),
                provider_factory=lambda task: MockProvider([
                    ModelResponse.tool_use(
                        tool_use_id="toolu_1",
                        name="write_file",
                        tool_input={"path": ".env", "content": "TOKEN=secret\n"},
                        text="I will write the file.",
                        model="mock-model",
                    ),
                    ModelResponse.text("Done.", model="mock-model"),
                ]),
                output_dir=Path(tempdir) / "benchmarks",
            )

            report = runner.run([spec], run_id="run-policy-failure")
            result = report.results[0]

        self.assertEqual(report.resolved_tasks, 0)
        self.assertFalse(result.resolved)
        self.assertEqual(result.status, "failed")
        self.assertTrue(result.metrics["verified_success"])
        self.assertTrue(result.metrics["patch_policy_failed"])

    def test_ablation_runner_writes_variant_reports_and_outcome_matrix(self):
        with tempfile.TemporaryDirectory() as tempdir:
            output_dir = Path(tempdir) / "benchmarks"
            spec = BenchmarkTaskSpec(
                task_id="constraint-ablation",
                goal="finish without edits",
                workspace_root=tempdir,
                verification_command=python_command("print('tests pass')"),
                permission_mode=PermissionMode.AUTO,
                enable_task_constraints=True,
                required_changed_paths=["src/*.py"],
            )
            runner = BenchmarkAblationRunner(
                base_config=Config(
                    model_provider="mock",
                    model="mock-model",
                    permission_mode=PermissionMode.AUTO,
                    enable_sandbox_artifacts=False,
                ),
                provider_factory=lambda task: MockProvider([
                    ModelResponse.text("Done.", model="mock-model")
                ]),
                output_dir=output_dir,
            )

            report = runner.run(
                [spec],
                variants=[
                    BenchmarkAblationVariant(name="baseline"),
                    BenchmarkAblationVariant(
                        name="no_task_constraints",
                        overrides={"enable_task_constraints": False},
                    ),
                ],
                run_id="ablation-run",
            )
            payload = json.loads(Path(report.report_path).read_text(encoding="utf-8"))
            baseline_report_exists = Path(
                payload["variant_results"][0]["report_path"]
            ).exists()

        baseline = report.variant_results[0].report.results[0]
        no_constraints = report.variant_results[1].report.results[0]
        variant_payloads = payload["variant_results"]
        matrix = payload["task_outcomes"][0]

        self.assertEqual(payload["schema_version"], BENCHMARK_ABLATION_SCHEMA_VERSION)
        self.assertEqual(report.total_task_runs, 2)
        self.assertFalse(baseline.resolved)
        self.assertTrue(no_constraints.resolved)
        self.assertEqual(variant_payloads[0]["summary"]["resolved_rate"], 0.0)
        self.assertEqual(variant_payloads[1]["summary"]["resolved_rate"], 1.0)
        self.assertEqual(variant_payloads[1]["summary"]["first_pass_success_rate"], 1.0)
        self.assertEqual(
            variant_payloads[1]["delta_vs_baseline"]["resolved_tasks"],
            1,
        )
        self.assertEqual(
            variant_payloads[1]["delta_vs_baseline"]["first_pass_success_tasks"],
            1,
        )
        self.assertEqual(matrix["improved_variants"], ["no_task_constraints"])
        self.assertTrue(baseline_report_exists)

    def test_report_summary_counts_first_pass_and_retry_recovery(self):
        task = BenchmarkTaskSpec(task_id="task", goal="demo")
        report = BenchmarkReport(
            run_id="run-summary",
            created_at="2026-07-31T00:00:00Z",
            output_dir=".",
            tasks=[task, task, task],
            results=[
                BenchmarkTaskResult(
                    task_id="first-pass",
                    goal="demo",
                    status="succeeded",
                    resolved=True,
                    duration_seconds=1.0,
                    metrics={
                        "turns": 2,
                        "tool_calls": 3,
                        "reflection_retry_count": 0,
                        "patch_policy_changed_files": 1,
                        "patch_policy_changed_lines": 4,
                    },
                ),
                BenchmarkTaskResult(
                    task_id="retry-recovered",
                    goal="demo",
                    status="succeeded",
                    resolved=True,
                    duration_seconds=2.0,
                    metrics={
                        "turns": 4,
                        "tool_calls": 6,
                        "reflection_retry_count": 1,
                        "patch_policy_changed_files": 2,
                        "patch_policy_changed_lines": 8,
                    },
                ),
                BenchmarkTaskResult(
                    task_id="retry-failed",
                    goal="demo",
                    status="failed",
                    resolved=False,
                    duration_seconds=3.0,
                    metrics={
                        "turns": 5,
                        "tool_calls": 7,
                        "reflection_retry_count": 1,
                        "patch_policy_changed_files": 3,
                        "patch_policy_changed_lines": 12,
                    },
                ),
            ],
        )

        summary = report.summary()

        self.assertEqual(summary["resolved_tasks"], 2)
        self.assertEqual(summary["first_pass_success_tasks"], 1)
        self.assertEqual(summary["first_pass_success_rate"], 0.333333)
        self.assertEqual(summary["retry_attempted_tasks"], 2)
        self.assertEqual(summary["retry_recovered_tasks"], 1)
        self.assertEqual(summary["retry_recovery_rate"], 0.5)
        self.assertEqual(summary["average_patch_changed_files"], 2.0)
        self.assertEqual(summary["average_patch_changed_lines"], 8.0)


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )


if __name__ == "__main__":
    unittest.main()
