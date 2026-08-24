import json
import tempfile
import unittest
from pathlib import Path

from codeagentx.evaluation import (
    BENCHMARK_ABLATION_SCHEMA_VERSION,
    BENCHMARK_SCHEMA_VERSION,
    render_benchmark_report_markdown,
    save_benchmark_report_markdown,
)


class BenchmarkReportingTests(unittest.TestCase):
    def test_renders_single_benchmark_report_markdown(self):
        markdown = render_benchmark_report_markdown({
            "schema_version": BENCHMARK_SCHEMA_VERSION,
            "run_id": "bench-1",
            "created_at": "2026-07-31T00:00:00Z",
            "output_dir": ".codeagentx/benchmarks/bench-1",
            "memory_policy": {"policy": "isolated"},
            "summary": {
                "total_tasks": 2,
                "resolved_tasks": 1,
                "failed_tasks": 1,
                "resolved_rate": 0.5,
                "first_pass_success_rate": 0.5,
                "retry_recovery_rate": 0.0,
                "average_tool_calls": 3.5,
                "average_budget_turns": 2.0,
                "average_budget_total_tokens": 42.0,
                "average_budget_elapsed_seconds": 1.25,
                "budget_exhausted_tasks": 1,
                "average_patch_changed_lines": 8.0,
                "average_git_diff_patch_bytes": 120.0,
                "average_git_diff_changed_files": 1.0,
                "average_memory_hits": 1.0,
                "average_memory_candidates": 2.0,
                "average_memory_filtered": 1.0,
                "average_memory_prompt_injected": 1.0,
                "average_memory_stored": 1.0,
                "artifact_count": 2,
            },
            "results": [
                {
                    "task_id": "task-a",
                    "resolved": True,
                    "status": "succeeded",
                    "verification_status": "passed",
                    "metrics": {
                        "tool_calls": 3,
                        "reflection_retry_count": 0,
                        "memory_hit_count": 1,
                        "memory_prompt_injected_count": 1,
                        "patch_policy_changed_lines": 4,
                        "git_diff_patch_bytes": 120,
                        "budget_exhausted": True,
                        "budget_total_tokens": 42,
                    },
                }
            ],
        })

        self.assertIn("# CodeAgent-X Benchmark Report", markdown)
        self.assertIn("- Memory Policy: `isolated`", markdown)
        self.assertIn("| resolved_rate | 50.0% |", markdown)
        self.assertIn(
            "| task-a | yes | succeeded | passed | 3 | 0 | 1 | 1 | 4 | 120 | yes | 42 |",
            markdown,
        )
        self.assertIn("| budget_exhausted_tasks | 1 |", markdown)
        self.assertIn("| average_git_diff_patch_bytes | 120 |", markdown)
        self.assertIn("| average_memory_hits | 1 |", markdown)
        self.assertIn("| average_memory_filtered | 1 |", markdown)

    def test_renders_swebench_official_evaluation_when_report_is_annotated(self):
        markdown = render_benchmark_report_markdown({
            "schema_version": BENCHMARK_SCHEMA_VERSION,
            "run_id": "swebench-1",
            "created_at": "2026-08-05T00:00:00Z",
            "output_dir": ".codeagentx/benchmarks/swebench-1",
            "summary": {
                "total_tasks": 2,
                "resolved_tasks": 0,
                "failed_tasks": 2,
                "resolved_rate": 0.0,
            },
            "swebench_official_evaluation": {
                "results_path": "official/results.json",
                "total_tasks": 2,
                "evaluated_tasks": 2,
                "resolved_tasks": 1,
                "unresolved_tasks": 1,
                "non_error_unresolved_tasks": 1,
                "error_tasks": 0,
                "missing_tasks": 0,
                "resolved_rate": 0.5,
                "evaluated_resolved_rate": 0.5,
            },
            "results": [
                {
                    "task_id": "owner__repo-1",
                    "resolved": False,
                    "official_resolved": True,
                    "official_status": "resolved",
                    "status": "failed",
                    "verification_status": "passed",
                    "metrics": {
                        "tool_calls": 4,
                        "reflection_retry_count": 0,
                        "memory_hit_count": 0,
                        "memory_prompt_injected_count": 0,
                        "patch_policy_changed_lines": 6,
                        "git_diff_patch_bytes": 300,
                        "budget_exhausted": False,
                        "budget_total_tokens": 100,
                    },
                },
                {
                    "task_id": "owner__repo-2",
                    "resolved": False,
                    "official_resolved": False,
                    "official_status": "unresolved",
                    "official_patch_successfully_applied": True,
                    "official_fail_to_pass_failed": [
                        "tests/test_fix.py::test_bug",
                        "tests/test_fix.py::test_edge",
                    ],
                    "official_pass_to_pass_failed": [],
                    "official_failure_summary": (
                        "FAILED tests/test_fix.py::test_bug - AssertionError"
                    ),
                    "official_log_path": "logs/run_evaluation/run-1/model/owner__repo-2/run_instance.log",
                    "status": "failed",
                    "verification_status": "failed",
                    "metrics": {},
                },
            ],
        })

        self.assertIn("## SWE-bench Official Evaluation", markdown)
        self.assertIn("| results_path | official/results.json |", markdown)
        self.assertIn("| evaluated_resolved_rate | 50.0% |", markdown)
        self.assertIn("| non_error_unresolved_tasks | 1 |", markdown)
        self.assertIn("| error_tasks | 0 |", markdown)
        self.assertIn("Official Resolved", markdown)
        self.assertIn(
            "| owner__repo-1 | no | yes | resolved | failed | passed | 4 | 0 | 0 | 0 | 6 | 300 | no | 100 |",
            markdown,
        )
        self.assertIn("## SWE-bench Failure Details", markdown)
        self.assertIn("Diagnostic", markdown)
        self.assertIn("Log", markdown)
        self.assertIn(
            "| owner__repo-2 | unresolved | yes | tests/test_fix.py::test_bug, tests/test_fix.py::test_edge |  | FAILED tests/test_fix.py::test_bug - AssertionError |  | logs/run_evaluation/run-1/model/owner__repo-2/run_instance.log |",
            markdown,
        )

    def test_renders_ablation_report_markdown(self):
        markdown = render_benchmark_report_markdown({
            "schema_version": BENCHMARK_ABLATION_SCHEMA_VERSION,
            "run_id": "abl-1",
            "created_at": "2026-07-31T00:00:00Z",
            "output_dir": ".codeagentx/benchmarks/abl-1",
            "summary": {
                "task_count": 1,
                "variant_count": 2,
                "baseline_variant": "baseline",
            },
            "variant_results": [
                {
                    "variant": {"name": "baseline"},
                    "memory_policy": {"policy": "isolated"},
                    "summary": {
                        "resolved_rate": 0.0,
                        "first_pass_success_rate": 0.0,
                        "retry_recovery_rate": 0.0,
                        "metric_averages": {
                            "tool_calls": 2.0,
                            "patch_policy_changed_lines": 0.0,
                            "memory_hit_count": 1.0,
                            "memory_filtered_count": 0.0,
                            "memory_prompt_injected_count": 1.0,
                        },
                    },
                    "delta_vs_baseline": {
                        "resolved_rate": 0.0,
                        "retry_recovery_rate": 0.0,
                    },
                },
                {
                    "variant": {"name": "no_task_constraints"},
                    "memory_policy": {"policy": "isolated"},
                    "summary": {
                        "resolved_rate": 1.0,
                        "first_pass_success_rate": 1.0,
                        "retry_recovery_rate": 0.0,
                        "metric_averages": {
                            "tool_calls": 2.0,
                            "patch_policy_changed_lines": 0.0,
                            "memory_hit_count": 0.0,
                            "memory_filtered_count": 2.0,
                            "memory_prompt_injected_count": 0.0,
                        },
                    },
                    "delta_vs_baseline": {
                        "resolved_rate": 1.0,
                        "retry_recovery_rate": 0.0,
                    },
                },
            ],
            "task_outcomes": [
                {
                    "task_id": "task-a",
                    "baseline_resolved": False,
                    "improved_variants": ["no_task_constraints"],
                    "regressed_variants": [],
                }
            ],
        })

        self.assertIn("# CodeAgent-X Benchmark Ablation Report", markdown)
        self.assertIn("- Memory Policy: `isolated`", markdown)
        self.assertIn("| no_task_constraints | isolated | 100.0% | 100.0% | 0.0% | 2 | 0 | 0 | 2 | 0 | +100.0% | +0.0% |", markdown)
        self.assertIn("| task-a | no | no_task_constraints |  |", markdown)

    def test_saves_markdown_next_to_report_by_default(self):
        with tempfile.TemporaryDirectory() as tempdir:
            report_path = Path(tempdir) / "report.json"
            report_path.write_text(
                json.dumps({
                    "schema_version": BENCHMARK_SCHEMA_VERSION,
                    "run_id": "bench-1",
                    "created_at": "2026-07-31T00:00:00Z",
                    "output_dir": tempdir,
                    "summary": {"total_tasks": 0},
                    "results": [],
                }),
                encoding="utf-8",
            )

            output_path = save_benchmark_report_markdown(report_path)

            self.assertEqual(output_path, report_path.with_suffix(".md"))
            self.assertTrue(output_path.exists())
            self.assertIn("CodeAgent-X Benchmark Report", output_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
