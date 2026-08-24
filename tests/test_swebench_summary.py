import json
import tempfile
import unittest
from pathlib import Path

from codeagentx.evaluation import (
    SWEBENCH_EXPERIMENT_SUMMARY_SCHEMA_VERSION,
    build_swebench_experiment_summary,
    render_swebench_experiment_summary_markdown,
    write_swebench_experiment_summary,
)


class SWEbenchExperimentSummaryTests(unittest.TestCase):
    def test_aggregates_annotated_reports_with_failure_categories(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            first_report = root / "report-a.json"
            second_report = root / "report-b.json"
            first_report.write_text(
                json.dumps(_report_payload(
                    run_id="run-a",
                    results=[
                        {
                            "task_id": "owner__repo-1",
                            "resolved": False,
                            "status": "failed",
                            "verification_status": "passed",
                            "official_resolved": True,
                            "official_status": "resolved",
                            "official_patch_successfully_applied": True,
                            "metrics": {
                                "tool_calls": 4,
                                "budget_total_tokens": 100,
                                "git_diff_patch_bytes": 200,
                                "git_diff_changed_files": 1,
                            },
                        },
                        {
                            "task_id": "owner__repo-2",
                            "resolved": False,
                            "status": "failed",
                            "verification_status": "failed",
                            "official_resolved": False,
                            "official_status": "unresolved",
                            "official_patch_successfully_applied": True,
                            "official_fail_to_pass_failed": [
                                "tests/test_fix.py::test_bug",
                                "tests/test_fix.py::test_edge",
                            ],
                            "metrics": {
                                "tool_calls": 6,
                                "budget_total_tokens": 300,
                                "git_diff_patch_bytes": 400,
                                "git_diff_changed_files": 2,
                            },
                        },
                    ],
                )),
                encoding="utf-8",
            )
            second_report.write_text(
                json.dumps(_report_payload(
                    run_id="run-b",
                    results=[
                        {
                            "task_id": "owner__repo-3",
                            "resolved": False,
                            "status": "failed",
                            "verification_status": "skipped",
                            "metrics": {
                                "tool_calls": 2,
                                "budget_total_tokens": 50,
                                "git_diff_patch_bytes": 0,
                            },
                        },
                    ],
                )),
                encoding="utf-8",
            )

            summary = build_swebench_experiment_summary([first_report, second_report])

        self.assertEqual(
            summary["schema_version"],
            SWEBENCH_EXPERIMENT_SUMMARY_SCHEMA_VERSION,
        )
        self.assertEqual(summary["report_count"], 2)
        self.assertEqual(summary["task_count"], 3)
        self.assertEqual(summary["evaluated_tasks"], 2)
        self.assertEqual(summary["official_resolved_tasks"], 1)
        self.assertEqual(summary["official_non_error_unresolved_tasks"], 1)
        self.assertEqual(summary["official_error_tasks"], 0)
        self.assertEqual(summary["official_missing_tasks"], 1)
        self.assertEqual(summary["official_resolved_rate"], 1 / 3)
        self.assertEqual(summary["evaluated_official_resolved_rate"], 0.5)
        self.assertEqual(summary["patch_generated_tasks"], 2)
        self.assertEqual(summary["patch_applied_tasks"], 2)
        self.assertEqual(summary["failure_category_counts"]["resolved"], 1)
        self.assertEqual(summary["failure_category_counts"]["hidden_tests_failed"], 1)
        self.assertEqual(summary["failure_category_counts"]["official_missing"], 1)
        self.assertEqual(summary["average_tool_calls"], 4.0)

    def test_counts_evaluator_errors_separately(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            report_path = root / "report.json"
            report_path.write_text(
                json.dumps(_report_payload(
                    run_id="run-error",
                    results=[
                        {
                            "task_id": "owner__repo-1",
                            "official_resolved": False,
                            "official_status": "error",
                            "metrics": {"git_diff_patch_bytes": 100},
                        },
                        {
                            "task_id": "owner__repo-2",
                            "official_resolved": False,
                            "official_status": "unresolved",
                            "metrics": {"git_diff_patch_bytes": 100},
                        },
                    ],
                )),
                encoding="utf-8",
            )

            summary = build_swebench_experiment_summary([report_path])
            markdown = render_swebench_experiment_summary_markdown(summary)

        self.assertEqual(summary["official_unresolved_tasks"], 2)
        self.assertEqual(summary["official_non_error_unresolved_tasks"], 1)
        self.assertEqual(summary["official_error_tasks"], 1)
        self.assertEqual(summary["failure_category_counts"]["evaluator_error"], 1)
        self.assertIn("| official_error_tasks | 1 |", markdown)

    def test_writes_json_and_markdown_summary_artifacts(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            report_path = root / "report.json"
            output_path = root / "summary.json"
            markdown_path = root / "summary.md"
            report_path.write_text(
                json.dumps(_report_payload(
                    run_id="run-a",
                    results=[
                        {
                            "task_id": "owner__repo-1",
                            "official_resolved": False,
                            "official_status": "unresolved",
                            "official_patch_successfully_applied": True,
                            "official_fail_to_pass_failed": [
                                "tests/test_fix.py::test_bug",
                            ],
                            "metrics": {
                                "tool_calls": 4,
                                "budget_total_tokens": 100,
                                "git_diff_patch_bytes": 200,
                            },
                        }
                    ],
                )),
                encoding="utf-8",
            )

            artifact = write_swebench_experiment_summary(
                [report_path],
                output_path,
                markdown_output_path=markdown_path,
            )
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            markdown = markdown_path.read_text(encoding="utf-8")

        self.assertEqual(artifact["summary_path"], output_path)
        self.assertEqual(artifact["markdown_path"], markdown_path)
        self.assertEqual(payload["failure_category_counts"]["hidden_tests_failed"], 1)
        self.assertIn("# SWE-bench Experiment Summary", markdown)
        self.assertIn("| hidden_tests_failed | 1 |", markdown)
        self.assertIn("tests/test_fix.py::test_bug", markdown)

    def test_renders_empty_summary_table_when_no_tasks_are_present(self):
        markdown = render_swebench_experiment_summary_markdown({
            "schema_version": SWEBENCH_EXPERIMENT_SUMMARY_SCHEMA_VERSION,
            "report_count": 1,
            "task_count": 0,
            "failure_category_counts": {},
            "tasks": [],
        })

        self.assertIn("## Tasks", markdown)
        self.assertIn("| Task | Run | Official | Category |", markdown)


def _report_payload(
    *,
    run_id: str,
    results: list[dict],
) -> dict:
    return {
        "schema_version": "codeagentx.benchmark.v1",
        "run_id": run_id,
        "created_at": "2026-08-06T00:00:00Z",
        "output_dir": f".codeagentx/swebench/runs/{run_id}",
        "memory_policy": {"policy": "disabled"},
        "swebench_official_evaluation": {
            "results_path": f".codeagentx/swebench/runs/{run_id}/official/results.json",
        },
        "results": results,
    }


if __name__ == "__main__":
    unittest.main()
