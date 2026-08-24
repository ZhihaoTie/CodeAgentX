from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codeagentx.evaluation import (
    SWEbenchEvaluatorConfig,
    annotate_benchmark_report_with_swebench_evaluation,
    build_swebench_predictions_from_report,
    load_swebench_official_outcomes,
    run_swebench_evaluation,
    write_swebench_predictions_from_report,
)


class SWEbenchEvaluatorAdapterTests(unittest.TestCase):
    def test_writes_predictions_jsonl_from_benchmark_report(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            patch_path = root / "patch.diff"
            patch_path.write_text(
                "diff --git a/app.py b/app.py\n"
                "--- a/app.py\n"
                "+++ b/app.py\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n",
                encoding="utf-8",
            )
            report_path = root / "report.json"
            report_path.write_text(
                json.dumps(_benchmark_report(str(patch_path))),
                encoding="utf-8",
            )
            output_path = root / "predictions.jsonl"

            artifact = write_swebench_predictions_from_report(
                report_path,
                output_path,
                model_name_or_path="codeagentx/mock",
            )
            rows = [
                json.loads(line)
                for line in output_path.read_text(encoding="utf-8").splitlines()
            ]
            manifest = json.loads(
                Path(artifact.manifest_path).read_text(encoding="utf-8")
            )

        self.assertEqual(artifact.prediction_count, 1)
        self.assertEqual(artifact.patch_generated_count, 1)
        self.assertEqual(artifact.empty_patch_count, 0)
        self.assertEqual(rows[0]["instance_id"], "owner__repo-1")
        self.assertEqual(rows[0]["model_name_or_path"], "codeagentx/mock")
        self.assertIn("+new", rows[0]["model_patch"])
        self.assertEqual(manifest["instance_ids"], ["owner__repo-1"])

    def test_can_skip_empty_patch_predictions(self):
        report = _benchmark_report(patch_path=None)

        with self.assertRaisesRegex(ValueError, "no SWE-bench predictions"):
            build_swebench_predictions_from_report(
                report,
                model_name_or_path="codeagentx/mock",
                include_empty_patches=False,
            )

        predictions = build_swebench_predictions_from_report(
            report,
            model_name_or_path="codeagentx/mock",
            include_empty_patches=True,
        )

        self.assertEqual(len(predictions), 1)
        self.assertEqual(predictions[0].model_patch, "")
        self.assertFalse(predictions[0].patch_generated)

    def test_filters_predictions_by_task_id_and_limit(self):
        report = _benchmark_report(patch_path=None)
        report["tasks"].extend([
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
            {
                "task_id": "owner__repo-3",
                "goal": "Fix a third issue.",
                "metadata": {
                    "swebench": {
                        "instance_id": "owner__repo-3",
                        "repo": "owner/repo",
                        "base_commit": "abc123",
                    }
                },
            },
        ])
        report["results"].extend([
            {"task_id": "owner__repo-2", "artifacts": []},
            {"task_id": "owner__repo-3", "artifacts": []},
        ])

        predictions = build_swebench_predictions_from_report(
            report,
            model_name_or_path="codeagentx/mock",
            task_ids=["owner__repo-2", "owner__repo-3"],
            limit=1,
        )

        self.assertEqual([item.instance_id for item in predictions], ["owner__repo-2"])

        with self.assertRaisesRegex(ValueError, "greater than 0"):
            build_swebench_predictions_from_report(
                report,
                model_name_or_path="codeagentx/mock",
                limit=0,
            )

    def test_builds_official_evaluator_command(self):
        config = SWEbenchEvaluatorConfig(
            dataset_name="SWE-bench/SWE-bench_Lite",
            split="test",
            run_id="run-1",
            max_workers=2,
            timeout_seconds=900,
            cache_level="base",
            clean=True,
            namespace=None,
            report_dir="reports",
            python_executable="python",
            force_rebuild=True,
            rewrite_reports=True,
        )

        argv = config.to_argv(
            "predictions.jsonl",
            instance_ids=["owner__repo-1", "owner__repo-2"],
        )

        self.assertEqual(argv[:3], ["python", "-m", "swebench.harness.run_evaluation"])
        self.assertIn("--predictions_path", argv)
        self.assertIn("predictions.jsonl", argv)
        self.assertIn("--dataset_name", argv)
        self.assertIn("SWE-bench/SWE-bench_Lite", argv)
        self.assertIn("--cache_level", argv)
        self.assertIn("base", argv)
        self.assertIn("--clean", argv)
        self.assertIn("true", argv)
        self.assertIn("--report_dir", argv)
        self.assertIn("reports", argv)
        self.assertIn("--instance_ids", argv)
        self.assertIn("owner__repo-2", argv)
        self.assertNotIn("--namespace", argv)

    def test_builds_official_evaluator_command_with_prefix(self):
        config = SWEbenchEvaluatorConfig(
            run_id="run-1",
            python_executable="python",
            command_prefix=["docker", "run", "--rm", "evaluator-image"],
            report_dir=".codeagentx\\reports",
            posix_paths=True,
        )

        argv = config.to_argv(".codeagentx\\predictions.jsonl")

        self.assertEqual(
            argv[:7],
            [
                "docker",
                "run",
                "--rm",
                "evaluator-image",
                "python",
                "-m",
                "swebench.harness.run_evaluation",
            ],
        )
        self.assertIn("--predictions_path", argv)
        self.assertIn(".codeagentx/predictions.jsonl", argv)
        self.assertIn("--report_dir", argv)
        self.assertIn(".codeagentx/reports", argv)

    def test_discovers_official_report_path_from_stdout(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            report_path = root / "model.run-1.json"
            report_path.write_text("{}", encoding="utf-8")
            config = SWEbenchEvaluatorConfig(
                run_id="run-1",
                python_executable="python",
                report_dir=str(root / "reports"),
            )

            with patch(
                "codeagentx.evaluation.swebench_evaluator.subprocess.run"
            ) as run:
                run.return_value = subprocess.CompletedProcess(
                    args=["python"],
                    returncode=0,
                    stdout=f"Report written to {report_path.name}\n",
                    stderr="",
                )
                result = run_swebench_evaluation(
                    "predictions.jsonl",
                    config=config,
                    cwd=root,
                )

            self.assertEqual(result.results_path, str(report_path))
            self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")
            self.assertEqual(run.call_args.kwargs["errors"], "replace")

    def test_loads_official_outcomes_from_resolved_id_summary(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "results.json"
            path.write_text(
                json.dumps({
                    "resolved_ids": ["owner__repo-1"],
                    "unresolved_ids": ["owner__repo-2"],
                    "error_ids": ["owner__repo-3"],
                }),
                encoding="utf-8",
            )

            outcomes = load_swebench_official_outcomes(path)

        self.assertTrue(outcomes["owner__repo-1"].resolved)
        self.assertFalse(outcomes["owner__repo-2"].resolved)
        self.assertEqual(outcomes["owner__repo-3"].status, "error")

    def test_loads_official_outcome_details_from_instance_report(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "report.json"
            path.write_text(
                json.dumps({
                    "owner__repo-1": {
                        "patch_exists": True,
                        "patch_successfully_applied": True,
                        "resolved": False,
                        "tests_status": {
                            "FAIL_TO_PASS": {
                                "success": ["tests/test_fix.py::test_a"],
                                "failure": ["tests/test_fix.py::test_b"],
                            },
                            "PASS_TO_PASS": {
                                "success": [],
                                "failure": ["tests/test_regression.py::test_c"],
                            },
                        },
                    }
                }),
                encoding="utf-8",
            )

            outcomes = load_swebench_official_outcomes(path)

        outcome = outcomes["owner__repo-1"]
        self.assertFalse(outcome.resolved)
        self.assertTrue(outcome.patch_successfully_applied)
        self.assertEqual(
            outcome.fail_to_pass_failed,
            ["tests/test_fix.py::test_b"],
        )
        self.assertEqual(
            outcome.pass_to_pass_failed,
            ["tests/test_regression.py::test_c"],
        )

    def test_loads_companion_run_log_for_patch_apply_error(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            results_path = root / "model.run-1.json"
            results_path.write_text(
                json.dumps({"error_ids": ["owner__repo-1"]}),
                encoding="utf-8",
            )
            log_path = (
                root
                / "logs"
                / "run_evaluation"
                / "run-1"
                / "model"
                / "owner__repo-1"
                / "run_instance.log"
            )
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                "2026-08-06 00:00:00,000 - INFO - >>>>> Patch Apply Failed:\n"
                "patching file app.py\n"
                "Hunk #1 FAILED at 10.\n",
                encoding="utf-8",
            )
            stale_log_path = (
                root
                / "logs"
                / "run_evaluation"
                / "old-run"
                / "model"
                / "owner__repo-1"
                / "run_instance.log"
            )
            stale_log_path.parent.mkdir(parents=True)
            stale_log_path.write_text(
                "2026-08-05 00:00:00,000 - INFO - stale failure\n",
                encoding="utf-8",
            )

            outcomes = load_swebench_official_outcomes(results_path)

        outcome = outcomes["owner__repo-1"]
        self.assertEqual(outcome.status, "error")
        self.assertEqual(outcome.log_path, str(log_path))
        self.assertIn("Patch Apply Failed", outcome.failure_summary)
        self.assertIn("Hunk #1 FAILED", outcome.failure_excerpt)

    def test_annotates_benchmark_report_with_official_results(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            patch_path = root / "patch.diff"
            patch_path.write_text("diff --git a/app.py b/app.py\n+fixed\n", encoding="utf-8")
            report_path = root / "report.json"
            payload = _benchmark_report(str(patch_path))
            payload["tasks"].append({
                "task_id": "owner__repo-2",
                "goal": "Fix another issue.",
                "metadata": {
                    "swebench": {
                        "instance_id": "owner__repo-2",
                        "repo": "owner/repo",
                        "base_commit": "abc123",
                    }
                },
            })
            payload["results"].append({
                "task_id": "owner__repo-2",
                "metrics": {},
                "artifacts": [],
            })
            report_path.write_text(json.dumps(payload), encoding="utf-8")
            results_path = root / "official.json"
            results_path.write_text(
                json.dumps({
                    "instance_results": [
                        {"instance_id": "owner__repo-1", "resolved": True},
                        {"instance_id": "owner__repo-2", "resolved": False},
                    ]
                }),
                encoding="utf-8",
            )

            output_path = annotate_benchmark_report_with_swebench_evaluation(
                report_path,
                results_path,
            )
            annotated = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(output_path.name, "report.swebench.json")
        self.assertEqual(
            annotated["swebench_official_evaluation"]["resolved_tasks"],
            1,
        )
        self.assertEqual(
            annotated["swebench_official_evaluation"]["evaluated_tasks"],
            2,
        )
        self.assertEqual(
            annotated["swebench_official_evaluation"]["non_error_unresolved_tasks"],
            1,
        )
        self.assertEqual(
            annotated["swebench_official_evaluation"]["error_tasks"],
            0,
        )
        self.assertTrue(annotated["results"][0]["official_resolved"])
        self.assertFalse(annotated["results"][1]["official_resolved"])
        self.assertTrue(
            annotated["results"][0]["metrics"]["swebench_official_resolved"]
        )

    def test_annotation_counts_official_evaluator_errors_separately(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            report_path = root / "report.json"
            payload = _benchmark_report(patch_path=None)
            report_path.write_text(json.dumps(payload), encoding="utf-8")
            results_path = root / "official.json"
            results_path.write_text(
                json.dumps({"error_ids": ["owner__repo-1"]}),
                encoding="utf-8",
            )

            output_path = annotate_benchmark_report_with_swebench_evaluation(
                report_path,
                results_path,
            )
            annotated = json.loads(output_path.read_text(encoding="utf-8"))

        official = annotated["swebench_official_evaluation"]
        self.assertEqual(official["evaluated_tasks"], 1)
        self.assertEqual(official["resolved_tasks"], 0)
        self.assertEqual(official["unresolved_tasks"], 1)
        self.assertEqual(official["non_error_unresolved_tasks"], 0)
        self.assertEqual(official["error_tasks"], 1)

    def test_annotation_merges_companion_instance_report_details(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            report_path = root / "report.json"
            report_path.write_text(
                json.dumps(_benchmark_report(patch_path=None)),
                encoding="utf-8",
            )
            results_path = root / "model.run-1.json"
            results_path.write_text(
                json.dumps({
                    "resolved_ids": [],
                    "unresolved_ids": ["owner__repo-1"],
                    "error_ids": [],
                }),
                encoding="utf-8",
            )
            instance_report = (
                root
                / "logs"
                / "run_evaluation"
                / "run-1"
                / "model"
                / "owner__repo-1"
                / "report.json"
            )
            instance_report.parent.mkdir(parents=True)
            instance_report.write_text(
                json.dumps({
                    "owner__repo-1": {
                        "patch_exists": True,
                        "patch_successfully_applied": True,
                        "resolved": False,
                        "tests_status": {
                            "FAIL_TO_PASS": {
                                "success": [],
                                "failure": ["tests/test_fix.py::test_bug"],
                            },
                            "PASS_TO_PASS": {
                                "success": ["tests/test_ok.py::test_existing"],
                                "failure": [],
                            },
                        },
                    }
                }),
                encoding="utf-8",
            )
            log_path = instance_report.parent / "run_instance.log"
            test_output_path = instance_report.parent / "test_output.txt"
            log_path.write_text(
                "2026-08-06 00:00:00,000 - INFO - Result for owner__repo-1: resolved: False\n",
                encoding="utf-8",
            )
            test_output_path.write_text(
                "=================================== FAILURES ===================================\n"
                "FAILED tests/test_fix.py::test_bug - AssertionError: expected fixed behavior\n",
                encoding="utf-8",
            )

            output_path = annotate_benchmark_report_with_swebench_evaluation(
                report_path,
                results_path,
            )
            annotated = json.loads(output_path.read_text(encoding="utf-8"))

        result = annotated["results"][0]
        outcome = annotated["swebench_official_evaluation"]["outcomes"]["owner__repo-1"]
        self.assertFalse(result["official_resolved"])
        self.assertTrue(result["official_patch_successfully_applied"])
        self.assertEqual(
            result["official_fail_to_pass_failed"],
            ["tests/test_fix.py::test_bug"],
        )
        self.assertEqual(
            result["metrics"]["swebench_official_fail_to_pass_failed_count"],
            1,
        )
        self.assertEqual(result["official_log_path"], str(log_path))
        self.assertEqual(result["official_test_output_path"], str(test_output_path))
        self.assertIn("FAILED tests/test_fix.py::test_bug", result["official_failure_summary"])
        self.assertIn("AssertionError", result["official_failure_excerpt"])
        self.assertEqual(
            outcome["fail_to_pass_failed"],
            ["tests/test_fix.py::test_bug"],
        )
        self.assertEqual(outcome["log_path"], str(log_path))


def _benchmark_report(patch_path: str | None) -> dict[str, object]:
    artifacts = []
    if patch_path is not None:
        artifacts.append({
            "kind": "git_diff",
            "patch_path": patch_path,
        })
    return {
        "schema_version": "codeagentx.benchmark.v1",
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
            }
        ],
        "results": [
            {
                "task_id": "owner__repo-1",
                "artifacts": artifacts,
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
