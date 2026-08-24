import json
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from codeagentx.cli import (
    build_parser,
    _filter_benchmark_variants,
    _filter_benchmark_tasks,
    _annotate_swebench_report_if_available,
    _load_swebench_report_reference,
    _load_swebench_benchmark_tasks,
    _load_swebench_report_tasks,
    _run_swebench_auto_preflight_if_needed,
    _run_swebench_report_auto_preflight_if_needed,
    _swebench_report_memory_policy,
    _swebench_model_name,
    _write_swebench_predictions_for_report,
    main,
)
from codeagentx.evaluation import BenchmarkAblationVariant, BenchmarkTaskSpec


class BenchmarkTaskFilterTests(unittest.TestCase):
    def test_filters_by_task_id_preserving_suite_order(self):
        tasks = [
            BenchmarkTaskSpec(task_id="a", goal="A"),
            BenchmarkTaskSpec(task_id="b", goal="B"),
            BenchmarkTaskSpec(task_id="c", goal="C"),
        ]

        selected = _filter_benchmark_tasks(tasks, task_ids=["c", "a"], limit=None)

        self.assertEqual([task.task_id for task in selected], ["a", "c"])

    def test_applies_limit_after_filtering(self):
        tasks = [
            BenchmarkTaskSpec(task_id="a", goal="A"),
            BenchmarkTaskSpec(task_id="b", goal="B"),
        ]

        selected = _filter_benchmark_tasks(tasks, task_ids=[], limit=1)

        self.assertEqual([task.task_id for task in selected], ["a"])

    def test_rejects_unknown_task_id(self):
        with self.assertRaisesRegex(ValueError, "unknown benchmark task id"):
            _filter_benchmark_tasks(
                [BenchmarkTaskSpec(task_id="a", goal="A")],
                task_ids=["missing"],
                limit=None,
            )

    def test_rejects_non_positive_limit(self):
        with self.assertRaisesRegex(ValueError, "greater than 0"):
            _filter_benchmark_tasks(
                [BenchmarkTaskSpec(task_id="a", goal="A")],
                task_ids=[],
                limit=0,
            )

    def test_filters_ablation_variants_preserving_suite_order(self):
        variants = [
            BenchmarkAblationVariant(name="baseline"),
            BenchmarkAblationVariant(name="no_context_ranking"),
            BenchmarkAblationVariant(name="no_long_term_memory"),
        ]

        selected = _filter_benchmark_variants(
            variants,
            variant_names=["no_long_term_memory", "baseline"],
        )

        self.assertEqual(
            [variant.name for variant in selected],
            ["baseline", "no_long_term_memory"],
        )

    def test_rejects_unknown_ablation_variant(self):
        with self.assertRaisesRegex(ValueError, "unknown benchmark variant"):
            _filter_benchmark_variants(
                [BenchmarkAblationVariant(name="baseline")],
                variant_names=["missing"],
            )


class SWEbenchReportModeTests(unittest.TestCase):
    def test_swebench_dry_run_writes_task_manifest_without_agent_run(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            task_path = root / "tasks.jsonl"
            task_path.write_text(
                "\n".join([
                    json.dumps({
                        "instance_id": "owner__repo-1",
                        "repo": "owner/repo",
                        "base_commit": "abc123",
                        "problem_statement": "Fix it.",
                        "FAIL_TO_PASS": ["hidden::test_bug"],
                    }),
                    json.dumps({
                        "instance_id": "owner__repo-2",
                        "repo": "owner/repo",
                        "base_commit": "def456",
                        "problem_statement": "Skip this one.",
                    }),
                ]),
                encoding="utf-8",
            )
            manifest_path = root / "manifest.json"
            stdout = StringIO()

            with redirect_stdout(stdout):
                exit_code = main([
                    "--swebench",
                    str(task_path),
                    "--swebench-dry-run",
                    "--benchmark-task-id",
                    "owner__repo-1",
                    "--benchmark-limit",
                    "1",
                    "--swebench-manifest-output",
                    str(manifest_path),
                ])
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertIn("SWE-bench dry run: 1 task(s)", stdout.getvalue())
        self.assertEqual(payload["task_ids"], ["owner__repo-1"])
        self.assertFalse(payload["workspace_plan"]["provisioning_performed"])
        self.assertEqual(payload["test_target_totals"]["FAIL_TO_PASS"], 1)

    def test_generates_predictions_from_existing_report_without_agent_run(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            first_patch_path = root / "patch-1.diff"
            first_patch_path.write_text(
                "diff --git a/app.py b/app.py\n+first\n",
                encoding="utf-8",
            )
            second_patch_path = root / "patch-2.diff"
            second_patch_path.write_text(
                "diff --git a/app.py b/app.py\n+second\n",
                encoding="utf-8",
            )
            report_path = root / "report.json"
            report_path.write_text(
                json.dumps({
                    "schema_version": "codeagentx.benchmark.v1",
                    "run_id": "run-123",
                    "tasks": [
                        {
                            "task_id": "owner__repo-1",
                            "goal": "Fix it.",
                            "metadata": {
                                "swebench": {
                                    "instance_id": "owner__repo-1",
                                    "repo": "owner/repo",
                                    "base_commit": "abc123",
                                }
                            },
                        },
                        {
                            "task_id": "owner__repo-2",
                            "goal": "Fix another issue.",
                            "metadata": {
                                "swebench": {
                                    "instance_id": "owner__repo-2",
                                    "repo": "owner/repo",
                                    "base_commit": "abc123",
                                }
                            },
                        },
                    ],
                    "results": [
                        {
                            "task_id": "owner__repo-1",
                            "artifacts": [{
                                "kind": "git_diff",
                                "patch_path": str(first_patch_path),
                            }],
                        },
                        {
                            "task_id": "owner__repo-2",
                            "artifacts": [{
                                "kind": "git_diff",
                                "patch_path": str(second_patch_path),
                            }],
                        },
                    ],
                }),
                encoding="utf-8",
            )
            predictions_path = root / "predictions.jsonl"
            stdout = StringIO()

            with redirect_stdout(stdout):
                exit_code = main([
                    "--swebench-report",
                    str(report_path),
                    "--benchmark-task-id",
                    "owner__repo-2",
                    "--swebench-predictions-output",
                    str(predictions_path),
                    "--provider",
                    "mock",
                    "--model",
                    "mock-model",
                ])
            rows = [
                json.loads(line)
                for line in predictions_path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(exit_code, 0)
        self.assertIn("SWE-bench source report:", stdout.getvalue())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["instance_id"], "owner__repo-2")
        self.assertIn("+second", rows[0]["model_patch"])

    def test_loads_swebench_report_reference_from_json(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            report_path = root / "report.json"
            report_path.write_text(
                json.dumps({
                    "schema_version": "codeagentx.benchmark.v1",
                    "run_id": "run-abc",
                    "output_dir": str(root / "out"),
                    "tasks": [],
                    "results": [],
                }),
                encoding="utf-8",
            )

            report = _load_swebench_report_reference(report_path)

        self.assertEqual(report.run_id, "run-abc")
        self.assertEqual(Path(report.report_path), report_path)
        self.assertEqual(Path(report.output_dir), root / "out")

    def test_loads_swebench_tasks_from_existing_report_for_preflight(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            report_path = root / "report.json"
            report_path.write_text(
                json.dumps({
                    "schema_version": "codeagentx.benchmark.v1",
                    "run_id": "run-abc",
                    "output_dir": str(root / "out"),
                    "tasks": [
                        {
                            "task_id": "owner__repo-1",
                            "goal": "Fix the parser.",
                            "metadata": {
                                "swebench": {
                                    "instance_id": "owner__repo-1",
                                    "repo": "owner/repo",
                                    "base_commit": "abc123",
                                    "FAIL_TO_PASS": "[\"hidden::test_bug\"]",
                                    "PASS_TO_PASS": ["hidden::test_existing"],
                                }
                            },
                        },
                        {
                            "task_id": "owner__repo-2",
                            "goal": "Skip this issue.",
                            "metadata": {
                                "swebench": {
                                    "instance_id": "owner__repo-2",
                                    "repo": "owner/repo",
                                    "base_commit": "def456",
                                }
                            },
                        },
                    ],
                    "results": [],
                }),
                encoding="utf-8",
            )
            args = build_parser().parse_args([
                "--swebench-report",
                str(report_path),
                "--benchmark-task-id",
                "owner__repo-1",
            ])
            report = _load_swebench_report_reference(report_path)

            tasks = _load_swebench_report_tasks(report, args)

        self.assertEqual([task.instance_id for task in tasks], ["owner__repo-1"])
        self.assertEqual(tasks[0].repo, "owner/repo")
        self.assertEqual(tasks[0].base_commit, "abc123")
        self.assertEqual(tasks[0].problem_statement, "Fix the parser.")
        self.assertEqual(tasks[0].fail_to_pass, ["hidden::test_bug"])
        self.assertEqual(tasks[0].pass_to_pass, ["hidden::test_existing"])

    def test_swebench_report_auto_preflight_failure_stops_before_predictions(self):
        preflight = SimpleNamespace(
            passed=False,
            checks=[object()],
            failure_count=1,
            warning_count=0,
            report_path="report-auto-preflight.json",
        )

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            report_path = root / "report.json"
            report_path.write_text(
                json.dumps({
                    "schema_version": "codeagentx.benchmark.v1",
                    "run_id": "run-abc",
                    "output_dir": str(root / "out"),
                    "tasks": [{
                        "task_id": "owner__repo-1",
                        "goal": "Fix it.",
                        "metadata": {
                            "swebench": {
                                "instance_id": "owner__repo-1",
                                "repo": "owner/repo",
                                "base_commit": "abc123",
                            }
                        },
                    }],
                    "results": [{
                        "task_id": "owner__repo-1",
                        "artifacts": [],
                    }],
                }),
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()

            with (
                patch(
                    "codeagentx.cli._run_swebench_report_auto_preflight_if_needed",
                    return_value=preflight,
                ) as preflight_gate,
                patch("codeagentx.cli._write_swebench_predictions_for_report") as predictions,
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                exit_code = main([
                    "--swebench-report",
                    str(report_path),
                    "--swebench-evaluate",
                    "--provider",
                    "mock",
                    "--model",
                    "mock-model",
                ])

        self.assertEqual(exit_code, 1)
        preflight_gate.assert_called_once()
        predictions.assert_not_called()
        self.assertIn("SWE-bench report auto preflight: failed", stdout.getvalue())
        self.assertIn("report-auto-preflight.json", stdout.getvalue())
        self.assertIn("automatic preflight failed", stderr.getvalue())

    def test_swebench_report_no_auto_preflight_bypasses_gate_helper(self):
        args = build_parser().parse_args([
            "--swebench-report",
            "report.json",
            "--swebench-evaluate",
            "--swebench-no-auto-preflight",
            "--provider",
            "mock",
            "--model",
            "mock-model",
        ])
        report = SimpleNamespace(report_path="report.json", output_dir="out")

        with patch("codeagentx.cli._load_swebench_report_tasks") as load_tasks:
            preflight = _run_swebench_report_auto_preflight_if_needed(report, args)

        self.assertIsNone(preflight)
        load_tasks.assert_not_called()

    def test_swebench_report_auto_preflight_uses_report_memory_policy(self):
        preflight = SimpleNamespace(passed=True)

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            report_path = root / "report.json"
            report_path.write_text(
                json.dumps({
                    "schema_version": "codeagentx.benchmark.v1",
                    "run_id": "run-abc",
                    "output_dir": str(root / "out"),
                    "memory_policy": {"policy": "disabled"},
                    "tasks": [{
                        "task_id": "owner__repo-1",
                        "goal": "Fix it.",
                        "metadata": {
                            "swebench": {
                                "instance_id": "owner__repo-1",
                                "repo": "owner/repo",
                                "base_commit": "abc123",
                            }
                        },
                    }],
                    "results": [],
                }),
                encoding="utf-8",
            )
            args = build_parser().parse_args([
                "--swebench-report",
                str(report_path),
                "--swebench-evaluate",
                "--provider",
                "mock",
                "--model",
                "mock-model",
            ])
            report = _load_swebench_report_reference(report_path)

            with patch(
                "codeagentx.cli._write_swebench_preflight_to_path",
                return_value=preflight,
            ) as writer:
                result = _run_swebench_report_auto_preflight_if_needed(report, args)
            report_memory_policy = _swebench_report_memory_policy(report, fallback="shared")

        self.assertIs(result, preflight)
        self.assertEqual(report_memory_policy, "disabled")
        self.assertEqual(writer.call_args.kwargs["memory_policy"], "disabled")

    def test_parser_accepts_swebench_summary_options(self):
        parser = build_parser()
        args = parser.parse_args([
            "--swebench-summary",
            "report-a.json",
            "report-b.json",
            "--swebench-summary-output",
            "summary.json",
            "--swebench-summary-markdown-output",
            "summary.md",
        ])

        self.assertEqual(args.swebench_summary, ["report-a.json", "report-b.json"])
        self.assertEqual(args.swebench_summary_output, "summary.json")
        self.assertEqual(args.swebench_summary_markdown_output, "summary.md")

    def test_swebench_summary_writes_json_and_markdown_without_agent_run(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            report_path = root / "report.json"
            report_path.write_text(
                json.dumps({
                    "schema_version": "codeagentx.benchmark.v1",
                    "run_id": "run-summary",
                    "created_at": "2026-08-06T00:00:00Z",
                    "output_dir": str(root / "out"),
                    "memory_policy": {"policy": "disabled"},
                    "results": [
                        {
                            "task_id": "owner__repo-1",
                            "official_resolved": False,
                            "official_status": "unresolved",
                            "official_patch_successfully_applied": True,
                            "official_fail_to_pass_failed": [
                                "tests/test_fix.py::test_bug",
                            ],
                            "metrics": {
                                "tool_calls": 5,
                                "budget_total_tokens": 123,
                                "git_diff_patch_bytes": 456,
                            },
                        }
                    ],
                }),
                encoding="utf-8",
            )
            summary_path = root / "summary.json"
            markdown_path = root / "summary.md"
            stdout = StringIO()

            with redirect_stdout(stdout):
                exit_code = main([
                    "--swebench-summary",
                    str(report_path),
                    "--swebench-summary-output",
                    str(summary_path),
                    "--swebench-summary-markdown-output",
                    str(markdown_path),
                    "--provider",
                    "mock",
                    "--model",
                    "mock-model",
                ])
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
            markdown = markdown_path.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertIn("SWE-bench summary: 1 task(s)", stdout.getvalue())
        self.assertEqual(payload["failure_category_counts"]["hidden_tests_failed"], 1)
        self.assertIn("tests/test_fix.py::test_bug", markdown)


@unittest.skipUnless(shutil.which("git"), "git executable is required")
class SWEbenchCliTaskLoaderTests(unittest.TestCase):
    def test_parser_accepts_swebench_options(self):
        parser = build_parser()
        args = parser.parse_args([
            "--swebench",
            "tasks.jsonl",
            "--swebench-dry-run",
            "--swebench-preflight",
            "--swebench-no-auto-preflight",
            "--benchmark-task-id",
            "owner__repo-1",
            "--benchmark-limit",
            "1",
            "--swebench-workspaces-root",
            "workspaces",
            "--swebench-repo-cache-root",
            "cache",
            "--swebench-refresh-cache",
            "--swebench-update-submodules",
            "--swebench-setup-command",
            "python -m pip install -e .",
            "--swebench-manifest-output",
            "manifest.json",
            "--swebench-preflight-output",
            "preflight.json",
            "--swebench-predictions-output",
            "predictions.jsonl",
            "--swebench-model-name",
            "codeagentx/test-model",
            "--swebench-skip-empty-patches",
            "--swebench-evaluate",
            "--swebench-eval-dataset",
            "SWE-bench/SWE-bench_Lite",
            "--swebench-eval-split",
            "test",
            "--swebench-eval-run-id",
            "eval-run",
            "--swebench-eval-max-workers",
            "2",
            "--swebench-eval-timeout",
            "900",
            "--swebench-eval-python-executable",
            "python",
            "--swebench-eval-command-prefix",
            "docker run --rm evaluator-image",
            "--swebench-eval-cache-level",
            "base",
            "--swebench-eval-clean",
            "--swebench-eval-no-namespace",
            "--swebench-eval-results-path",
            "official.json",
            "--swebench-eval-artifact-output",
            "eval-artifact.json",
            "--swebench-docker-lifecycle-image",
            "python:3.11-slim",
            "--swebench-annotated-report-output",
            "annotated.json",
            "--benchmark-memory-policy",
            "isolated",
            "--verify-command",
            "python -m pytest",
        ])

        self.assertEqual(args.swebench, "tasks.jsonl")
        self.assertTrue(args.swebench_dry_run)
        self.assertTrue(args.swebench_preflight)
        self.assertTrue(args.swebench_no_auto_preflight)
        self.assertEqual(args.benchmark_task_id, ["owner__repo-1"])
        self.assertEqual(args.benchmark_limit, 1)
        self.assertTrue(args.swebench_refresh_cache)
        self.assertTrue(args.swebench_update_submodules)
        self.assertEqual(args.swebench_setup_command, "python -m pip install -e .")
        self.assertEqual(args.swebench_manifest_output, "manifest.json")
        self.assertEqual(args.swebench_preflight_output, "preflight.json")
        self.assertEqual(args.swebench_predictions_output, "predictions.jsonl")
        self.assertEqual(args.swebench_model_name, "codeagentx/test-model")
        self.assertTrue(args.swebench_skip_empty_patches)
        self.assertTrue(args.swebench_evaluate)
        self.assertEqual(args.swebench_eval_run_id, "eval-run")
        self.assertEqual(args.swebench_eval_max_workers, 2)
        self.assertEqual(args.swebench_eval_timeout, 900)
        self.assertEqual(args.swebench_eval_python_executable, "python")
        self.assertEqual(args.swebench_eval_command_prefix, "docker run --rm evaluator-image")
        self.assertEqual(args.swebench_eval_cache_level, "base")
        self.assertTrue(args.swebench_eval_clean)
        self.assertTrue(args.swebench_eval_no_namespace)
        self.assertEqual(args.swebench_eval_results_path, "official.json")
        self.assertEqual(args.swebench_eval_artifact_output, "eval-artifact.json")
        self.assertEqual(args.swebench_docker_lifecycle_image, "python:3.11-slim")
        self.assertEqual(args.swebench_annotated_report_output, "annotated.json")
        self.assertEqual(args.benchmark_memory_policy, "isolated")
        self.assertEqual(args.verify_command, "python -m pytest")

    def test_swebench_preflight_writes_report_without_agent_run(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            task_path = root / "tasks.jsonl"
            task_path.write_text(
                json.dumps({
                    "instance_id": "owner__repo-1",
                    "repo": "owner/repo",
                    "base_commit": "abc123",
                    "problem_statement": "Fix it.",
                }) + "\n",
                encoding="utf-8",
            )
            report_path = root / "preflight.json"
            stdout = StringIO()

            with redirect_stdout(stdout):
                exit_code = main([
                    "--swebench",
                    str(task_path),
                    "--swebench-preflight",
                    "--swebench-preflight-output",
                    str(report_path),
                    "--benchmark-memory-policy",
                    "disabled",
                    "--provider",
                    "mock",
                    "--model",
                    "mock-model",
                ])
            payload = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertIn("SWE-bench preflight: passed", stdout.getvalue())
        self.assertEqual(payload["task_ids"], ["owner__repo-1"])
        self.assertTrue(payload["summary"]["passed"])

    def test_swebench_auto_preflight_failure_stops_before_provisioning(self):
        preflight = SimpleNamespace(
            passed=False,
            checks=[object()],
            failure_count=1,
            warning_count=0,
            report_path="auto-preflight.json",
        )

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            task_path = root / "tasks.jsonl"
            task_path.write_text(
                json.dumps({
                    "instance_id": "owner__repo-1",
                    "repo": "owner/repo",
                    "base_commit": "abc123",
                    "problem_statement": "Fix it.",
                }) + "\n",
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()

            with (
                patch(
                    "codeagentx.cli._run_swebench_auto_preflight_if_needed",
                    return_value=preflight,
                ) as preflight_gate,
                patch("codeagentx.cli._load_swebench_benchmark_tasks") as load_tasks,
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                exit_code = main([
                    "--swebench",
                    str(task_path),
                    "--swebench-evaluate",
                    "--benchmark-memory-policy",
                    "disabled",
                    "--provider",
                    "mock",
                    "--model",
                    "mock-model",
                ])

        self.assertEqual(exit_code, 1)
        preflight_gate.assert_called_once()
        load_tasks.assert_not_called()
        self.assertIn("SWE-bench auto preflight: failed", stdout.getvalue())
        self.assertIn("auto-preflight.json", stdout.getvalue())
        self.assertIn("automatic preflight failed", stderr.getvalue())

    def test_swebench_no_auto_preflight_bypasses_gate_helper(self):
        args = build_parser().parse_args([
            "--swebench",
            "tasks.jsonl",
            "--swebench-evaluate",
            "--swebench-no-auto-preflight",
            "--provider",
            "mock",
            "--model",
            "mock-model",
        ])

        with patch("codeagentx.cli._load_swebench_manifest_tasks") as load_tasks:
            preflight = _run_swebench_auto_preflight_if_needed(args)

        self.assertIsNone(preflight)
        load_tasks.assert_not_called()

    def test_loads_swebench_jsonl_and_provisions_benchmark_tasks(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            source = root / "source-repo"
            source.mkdir()
            _git(source, "init")
            _git(source, "config", "user.email", "tester@example.com")
            _git(source, "config", "user.name", "Tester")
            (source / "app.py").write_text("version = 1\n", encoding="utf-8")
            _git(source, "add", ".")
            _git(source, "commit", "-m", "initial")
            base_commit = _git_output(source, "rev-parse", "HEAD")
            (source / "app.py").write_text("version = 2\n", encoding="utf-8")
            _git(source, "commit", "-am", "later")

            task_path = root / "tasks.jsonl"
            task_path.write_text(
                "\n".join([
                    json.dumps({
                        "instance_id": "owner__repo-1",
                        "repo": str(source),
                        "base_commit": base_commit,
                        "problem_statement": "Fix it.",
                    }),
                    json.dumps({
                        "instance_id": "owner__repo-2",
                        "repo": str(source),
                        "base_commit": base_commit,
                        "problem_statement": "Skip this one.",
                    }),
                ]),
                encoding="utf-8",
            )
            args = build_parser().parse_args([
                "--swebench",
                str(task_path),
                "--benchmark-task-id",
                "owner__repo-1",
                "--benchmark-limit",
                "1",
                "--swebench-workspaces-root",
                str(root / "workspaces"),
                "--swebench-repo-cache-root",
                str(root / "cache"),
                "--swebench-git-timeout",
                "30",
                "--swebench-setup-command",
                "python -m pip install -e .",
                "--verify-command",
                "python -m pytest",
            ])

            tasks = _load_swebench_benchmark_tasks(args)
            workspace = Path(tasks[0].workspace_root)
            workspace_text = (workspace / "app.py").read_text(encoding="utf-8")

        self.assertEqual([task.task_id for task in tasks], ["owner__repo-1"])
        self.assertEqual(tasks[0].repository_commit, base_commit)
        self.assertEqual(tasks[0].setup_command, "python -m pip install -e .")
        self.assertEqual(tasks[0].verification_command, "python -m pytest")
        self.assertTrue(tasks[0].enable_git_diff_artifact)
        self.assertEqual(workspace_text, "version = 1\n")
        self.assertTrue(tasks[0].metadata["swebench_workspace"]["prepared"])

    def test_writes_predictions_for_swebench_report(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            patch_path = root / "patch.diff"
            patch_path.write_text(
                "diff --git a/app.py b/app.py\n+fixed\n",
                encoding="utf-8",
            )
            report_path = root / "report.json"
            report_path.write_text(
                json.dumps({
                    "schema_version": "codeagentx.benchmark.v1",
                    "tasks": [{
                        "task_id": "owner__repo-1",
                        "goal": "Fix it.",
                        "metadata": {
                            "swebench": {
                                "instance_id": "owner__repo-1",
                                "repo": "owner/repo",
                                "base_commit": "abc123",
                            }
                        },
                    }],
                    "results": [{
                        "task_id": "owner__repo-1",
                        "artifacts": [{
                            "kind": "git_diff",
                            "patch_path": str(patch_path),
                        }],
                    }],
                }),
                encoding="utf-8",
            )
            args = SimpleNamespace(
                swebench_predictions_output=None,
                swebench_model_name=None,
                provider="mock",
                model="mock-model",
                swebench_skip_empty_patches=False,
            )
            report = SimpleNamespace(
                report_path=str(report_path),
                output_dir=str(root / "bench-output"),
            )

            artifact = _write_swebench_predictions_for_report(report, args)
            rows = [
                json.loads(line)
                for line in Path(artifact.predictions_path).read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(_swebench_model_name(args), "codeagentx/mock/mock-model")
        self.assertEqual(artifact.prediction_count, 1)
        self.assertEqual(rows[0]["instance_id"], "owner__repo-1")
        self.assertIn("+fixed", rows[0]["model_patch"])

    def test_swebench_report_can_write_repair_benchmark_spec(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            report_path = root / "report.swebench.json"
            output_path = root / "repair.json"
            report_path.write_text(
                json.dumps({
                    "schema_version": "codeagentx.benchmark.v1",
                    "run_id": "run-repair",
                    "output_dir": str(root / "out"),
                    "tasks": [{
                        "task_id": "owner__repo-1",
                        "goal": "Fix it.",
                        "workspace_root": "clean/workspace",
                        "metadata": {
                            "swebench": {
                                "instance_id": "owner__repo-1",
                                "repo": "owner/repo",
                                "base_commit": "abc123",
                            }
                        },
                    }],
                    "results": [{
                        "task_id": "owner__repo-1",
                        "official_resolved": False,
                        "official_status": "unresolved",
                        "official_failure_summary": "AssertionError: still broken",
                        "original_workspace_root": "clean/workspace",
                        "artifacts": [],
                    }],
                }),
                encoding="utf-8",
            )
            stdout = StringIO()

            with redirect_stdout(stdout):
                exit_code = main([
                    "--swebench-report",
                    str(report_path),
                    "--swebench-repair-output",
                    str(output_path),
                    "--provider",
                    "mock",
                    "--model",
                    "mock-model",
                ])
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertIn("Repair benchmark spec:", stdout.getvalue())
        self.assertIn("diagnostic-only", stdout.getvalue())
        self.assertEqual(payload["repair_task_count"], 1)
        self.assertIn("AssertionError: still broken", payload["tasks"][0]["goal"])

    def test_annotates_swebench_report_when_results_path_exists(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            report_path = root / "report.json"
            report_path.write_text(
                json.dumps({
                    "schema_version": "codeagentx.benchmark.v1",
                    "tasks": [{
                        "task_id": "owner__repo-1",
                        "goal": "Fix it.",
                        "metadata": {
                            "swebench": {
                                "instance_id": "owner__repo-1",
                                "repo": "owner/repo",
                                "base_commit": "abc123",
                            }
                        },
                    }],
                    "results": [{
                        "task_id": "owner__repo-1",
                        "metrics": {},
                        "artifacts": [],
                    }],
                }),
                encoding="utf-8",
            )
            results_path = root / "official.json"
            results_path.write_text(
                json.dumps({"resolved_ids": ["owner__repo-1"]}),
                encoding="utf-8",
            )
            output_path = root / "annotated.json"
            report = SimpleNamespace(report_path=str(report_path))
            args = SimpleNamespace(
                swebench_eval_results_path=str(results_path),
                swebench_annotated_report_output=str(output_path),
            )

            path = _annotate_swebench_report_if_available(report, None, args)
            annotated = json.loads(Path(path).read_text(encoding="utf-8"))

        self.assertEqual(Path(path), output_path)
        self.assertTrue(annotated["results"][0]["official_resolved"])


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )


def _git_output(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout.strip()


if __name__ == "__main__":
    unittest.main()
