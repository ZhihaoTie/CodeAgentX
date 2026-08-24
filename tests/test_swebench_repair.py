from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from codeagentx.evaluation import (
    SWEBENCH_REPAIR_BENCHMARK_SCHEMA_VERSION,
    build_swebench_repair_tasks_from_report,
    load_benchmark_spec,
    write_swebench_repair_benchmark_spec,
)


class SWEbenchRepairTests(unittest.TestCase):
    def test_builds_repair_tasks_from_official_failures(self):
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
            report_path = root / "report.swebench.json"
            payload = _annotated_report(patch_path)
            tasks = build_swebench_repair_tasks_from_report(
                payload,
                report_path=report_path,
            )

        self.assertEqual(len(tasks), 1)
        task = tasks[0]
        self.assertEqual(task.task_id, "owner__repo-1")
        self.assertEqual(task.workspace_root, "clean/workspace")
        self.assertIn("Diagnostic repair pass:", task.goal)
        self.assertIn("ValueError: bad edge case", task.goal)
        self.assertIn("tests/test_bug.py::test_hidden", task.goal)
        self.assertIn("+new", task.goal)
        self.assertIn("diagnostic-only", task.tags)
        self.assertFalse(
            task.metadata["swebench_repair"]["public_benchmark_fairness"]
        )
        self.assertNotIn("test_patch", task.metadata["swebench"]["metadata"])

    def test_write_repair_spec_is_loadable_as_benchmark(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            patch_path = root / "patch.diff"
            patch_path.write_text("diff --git a/app.py b/app.py\n+new\n", encoding="utf-8")
            report_path = root / "report.swebench.json"
            report_path.write_text(
                json.dumps(_annotated_report(patch_path)),
                encoding="utf-8",
            )
            output_path = root / "repair.json"

            artifact = write_swebench_repair_benchmark_spec(
                report_path,
                output_path,
            )
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            loaded = load_benchmark_spec(output_path)

        self.assertEqual(artifact.repair_task_count, 1)
        self.assertEqual(payload["schema_version"], SWEBENCH_REPAIR_BENCHMARK_SCHEMA_VERSION)
        self.assertFalse(payload["public_benchmark_fairness"])
        self.assertEqual([task.task_id for task in loaded], ["owner__repo-1"])
        self.assertIn("official-feedback", loaded[0].tags)


def _annotated_report(patch_path: Path) -> dict[str, object]:
    return {
        "schema_version": "codeagentx.benchmark.v1",
        "run_id": "run-1",
        "output_dir": "out",
        "tasks": [
            {
                "task_id": "owner__repo-1",
                "goal": "Fix the original issue.",
                "workspace_root": "clean/workspace",
                "repository_commit": "abc123",
                "enable_git_diff_artifact": True,
                "git_diff_base_ref": "abc123",
                "tags": ["swe-bench"],
                "metadata": {
                    "swebench": {
                        "instance_id": "owner__repo-1",
                        "repo": "owner/repo",
                        "base_commit": "abc123",
                        "metadata": {
                            "test_patch": "gold tests should not be copied",
                            "difficulty": "lite",
                        },
                    }
                },
            },
            {
                "task_id": "owner__repo-2",
                "goal": "Already done.",
                "workspace_root": "clean/workspace-2",
                "metadata": {
                    "swebench": {
                        "instance_id": "owner__repo-2",
                        "repo": "owner/repo",
                        "base_commit": "def456",
                    }
                },
            },
        ],
        "results": [
            {
                "task_id": "owner__repo-1",
                "official_resolved": False,
                "official_status": "unresolved",
                "official_patch_successfully_applied": True,
                "official_fail_to_pass_failed": ["tests/test_bug.py::test_hidden"],
                "official_failure_summary": "ValueError: bad edge case",
                "official_failure_excerpt": "FAILED tests/test_bug.py::test_hidden",
                "original_workspace_root": "clean/workspace",
                "artifacts": [
                    {
                        "kind": "git_diff",
                        "patch_path": str(patch_path),
                    }
                ],
            },
            {
                "task_id": "owner__repo-2",
                "official_resolved": True,
                "official_status": "resolved",
                "artifacts": [],
            },
        ],
    }


if __name__ == "__main__":
    unittest.main()
