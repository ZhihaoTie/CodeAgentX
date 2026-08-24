from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from codeagentx.evaluation import (
    SWEBENCH_TASK_MANIFEST_SCHEMA_VERSION,
    SWEbenchTaskSpec,
    build_swebench_task_manifest,
    load_swebench_tasks,
    write_swebench_task_manifest,
)


class SWEbenchAdapterTests(unittest.TestCase):
    def test_loads_jsonl_tasks_and_filters(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "tasks.jsonl"
            rows = [
                {
                    "instance_id": "repo__task-1",
                    "repo": "owner/repo",
                    "base_commit": "abc123",
                    "problem_statement": "Fix the parser.",
                    "FAIL_TO_PASS": ["tests/test_parser.py::test_bug"],
                    "PASS_TO_PASS": ["tests/test_parser.py::test_existing"],
                    "version": "1.0",
                    "patch": "gold patch should not be retained",
                    "difficulty": "mini",
                },
                {
                    "instance_id": "repo__task-2",
                    "repo": "owner/repo",
                    "base_commit": "def456",
                    "problem_statement": "Fix the renderer.",
                },
            ]
            path.write_text(
                "\n".join(json.dumps(row) for row in rows),
                encoding="utf-8",
            )

            tasks = load_swebench_tasks(path, task_ids=["repo__task-1"], limit=1)

        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].instance_id, "repo__task-1")
        self.assertEqual(tasks[0].fail_to_pass, ["tests/test_parser.py::test_bug"])
        self.assertEqual(tasks[0].pass_to_pass, ["tests/test_parser.py::test_existing"])
        self.assertEqual(tasks[0].metadata, {"difficulty": "mini"})

    def test_parses_json_encoded_grader_target_lists(self):
        task = SWEbenchTaskSpec.from_dict({
            "instance_id": "repo__task-1",
            "repo": "owner/repo",
            "base_commit": "abc123",
            "problem_statement": "Fix the parser without mentioning hidden tests.",
            "FAIL_TO_PASS": json.dumps([
                "tests/test_parser.py::test_bug",
                "tests/test_parser.py::test_edge",
            ]),
            "PASS_TO_PASS": json.dumps([
                "tests/test_parser.py::test_existing",
            ]),
        })

        manifest = build_swebench_task_manifest([task], workspaces_root=None)

        self.assertEqual(task.fail_to_pass, [
            "tests/test_parser.py::test_bug",
            "tests/test_parser.py::test_edge",
        ])
        self.assertEqual(task.pass_to_pass, ["tests/test_parser.py::test_existing"])
        self.assertEqual(manifest.total_fail_to_pass, 2)
        self.assertEqual(manifest.total_pass_to_pass, 1)
        self.assertEqual(manifest.prompt_leakage_count, 0)

    def test_converts_to_benchmark_task_without_leaking_grader_tests_in_goal(self):
        task = SWEbenchTaskSpec(
            instance_id="repo__task-1",
            repo="owner/repo",
            base_commit="abc123",
            problem_statement="Fix the parser.",
            fail_to_pass=["hidden::test_bug"],
            pass_to_pass=["hidden::test_existing"],
        )

        benchmark_task = task.to_benchmark_task(
            workspace_root="workspaces/repo__task-1",
            verification_command="python -m pytest",
            setup_command="python -m pip install -e .",
        )

        self.assertEqual(benchmark_task.task_id, "repo__task-1")
        self.assertEqual(benchmark_task.repository_commit, "abc123")
        self.assertTrue(benchmark_task.enable_git_diff_artifact)
        self.assertEqual(benchmark_task.git_diff_base_ref, "abc123")
        self.assertEqual(benchmark_task.workspace_root, "workspaces/repo__task-1")
        self.assertEqual(benchmark_task.verification_command, "python -m pytest")
        self.assertIn("swe-bench", benchmark_task.tags)
        self.assertIn("Fix the parser.", benchmark_task.goal)
        self.assertIn("Do not leave ad-hoc scratch", benchmark_task.goal)
        self.assertNotIn("hidden::test_bug", benchmark_task.goal)
        self.assertIn("test_fix.py", benchmark_task.forbidden_changed_paths)
        self.assertIn("test_*_fix.py", benchmark_task.forbidden_changed_paths)
        self.assertEqual(
            benchmark_task.metadata["swebench"]["FAIL_TO_PASS"],
            ["hidden::test_bug"],
        )

    def test_builds_dry_run_manifest_without_provisioning(self):
        task = SWEbenchTaskSpec(
            instance_id="repo__task-1",
            repo="owner/repo",
            base_commit="abc123",
            problem_statement="Fix the parser.",
            fail_to_pass=["hidden::test_bug"],
            pass_to_pass=["hidden::test_existing"],
            version="1.0",
            environment={"python": "3.11"},
            metadata={"difficulty": "lite"},
        )

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            output_path = root / "manifest.json"
            manifest = write_swebench_task_manifest(
                [task],
                output_path,
                source_path=root / "tasks.jsonl",
                selected_task_ids=["repo__task-1"],
                limit=1,
                workspaces_root=root / "workspaces",
            )
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(manifest.task_count, 1)
        self.assertEqual(payload["schema_version"], SWEBENCH_TASK_MANIFEST_SCHEMA_VERSION)
        self.assertEqual(payload["task_ids"], ["repo__task-1"])
        self.assertEqual(payload["test_target_totals"]["FAIL_TO_PASS"], 1)
        self.assertFalse(payload["entries"][0]["prompt_contains_grader_tests"])
        self.assertEqual(payload["entries"][0]["environment_keys"], ["python"])
        self.assertEqual(payload["entries"][0]["metadata_keys"], ["difficulty"])
        self.assertFalse(payload["workspace_plan"]["provisioning_performed"])
        self.assertIn("repo__task-1", payload["entries"][0]["estimated_workspace_root"])

    def test_manifest_flags_prompt_grader_test_leakage(self):
        task = SWEbenchTaskSpec(
            instance_id="repo__task-2",
            repo="owner/repo",
            base_commit="abc123",
            problem_statement="Please inspect hidden::test_bug behavior.",
            fail_to_pass=["hidden::test_bug"],
        )

        manifest = build_swebench_task_manifest([task], workspaces_root=None)

        self.assertEqual(manifest.prompt_leakage_count, 1)
        self.assertTrue(manifest.entries[0].prompt_contains_grader_tests)
        self.assertEqual(manifest.entries[0].visible_grader_test_count, 1)
        self.assertIsNone(manifest.entries[0].estimated_workspace_root)

    def test_rejects_missing_required_fields(self):
        with self.assertRaisesRegex(ValueError, "base_commit"):
            SWEbenchTaskSpec.from_dict({
                "instance_id": "x",
                "repo": "owner/repo",
                "problem_statement": "Fix it.",
            })


if __name__ == "__main__":
    unittest.main()
