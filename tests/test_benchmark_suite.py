import subprocess
import unittest
from pathlib import Path

from codeagentx.evaluation.benchmark import load_benchmark_ablation_spec, load_benchmark_spec


REPO_ROOT = Path(__file__).resolve().parents[1]
SUITE_PATH = REPO_ROOT / "benchmarks" / "suite-v0.json"


class BenchmarkSuiteV0Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks = load_benchmark_spec(SUITE_PATH)

    def test_suite_contains_expected_tasks(self):
        task_ids = [task.task_id for task in self.tasks]

        self.assertEqual(
            task_ids,
            [
                "py-math-bug-fix",
                "py-string-slug-normalization",
                "py-order-total-multifile",
                "py-task-constraints-no-docs",
                "js-static-todo-toggle",
                "ts-static-export-surface",
                "py-cli-flag-parsing",
                "py-config-merge-no-mutation",
                "js-static-remove-todo",
                "ts-static-union-render",
                "py-dedupe-users-preserve-first",
                "py-query-params-stable-encoding",
                "py-retry-backoff-cap",
                "py-sales-summary-filter-refunds",
                "py-moving-average-window",
                "js-static-priority-sort-copy",
                "js-static-visible-items-filter",
                "ts-static-user-display-fallback",
                "ts-static-route-builder-encoding",
                "py-markdown-links-extraction",
            ],
        )

    def test_tasks_are_self_contained_and_constrained(self):
        for task in self.tasks:
            with self.subTest(task=task.task_id):
                self.assertTrue(Path(task.workspace_root).exists())
                self.assertTrue(task.verification_command)
                self.assertTrue(task.success_criteria)
                self.assertTrue(task.enable_task_constraints)
                self.assertTrue(task.required_changed_paths)
                self.assertIn("tests/*", task.forbidden_changed_paths)
                self.assertTrue(task.enable_runtime_planning)
                self.assertTrue(task.enable_context_ranking)
                self.assertTrue(task.enable_long_term_memory)
                self.assertEqual(task.memory_retrieval_limit, 3)
                self.assertEqual(task.memory_min_score, 60)
                self.assertTrue(task.enable_failure_reflection)
                self.assertTrue(task.enable_retry_strategy_matrix)
                self.assertTrue(task.enable_tool_planning_guidance)

    def test_suite_declares_ablation_variants(self):
        _, variants = load_benchmark_ablation_spec(SUITE_PATH)
        variant_names = [variant.name for variant in variants]

        self.assertEqual(
            variant_names,
            [
                "baseline",
                "no_runtime_planning",
                "no_context_ranking",
                "no_long_term_memory",
                "no_failure_reflection",
                "no_retry_strategy_matrix",
                "no_tool_planning_guidance",
                "no_task_constraints",
                "no_patch_policy",
            ],
        )

    def test_fixture_verification_commands_start_failing(self):
        for task in self.tasks:
            with self.subTest(task=task.task_id):
                result = subprocess.run(
                    task.verification_command,
                    cwd=Path(task.workspace_root),
                    shell=True,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=10,
                )

                self.assertNotEqual(
                    result.returncode,
                    0,
                    msg=f"{task.task_id} should start as an unfixed benchmark fixture.",
                )


if __name__ == "__main__":
    unittest.main()
