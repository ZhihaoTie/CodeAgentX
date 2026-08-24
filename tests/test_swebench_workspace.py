from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from codeagentx.evaluation import SWEbenchTaskSpec, SWEbenchWorkspaceProvisioner


@unittest.skipUnless(shutil.which("git"), "git executable is required")
class SWEbenchWorkspaceProvisionerTests(unittest.TestCase):
    def test_provisions_local_repo_at_base_commit_with_cache(self):
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

            task = SWEbenchTaskSpec(
                instance_id="owner__repo-1",
                repo=str(source),
                base_commit=base_commit,
                problem_statement="Restore expected behavior.",
            )
            provisioner = SWEbenchWorkspaceProvisioner(
                workspaces_root=root / "workspaces",
                repo_cache_root=root / "cache",
                timeout_seconds=30,
            )

            report = provisioner.prepare_task(task)
            workspace = Path(report.workspace_root)
            workspace_text = (workspace / "app.py").read_text(encoding="utf-8")
            cache_path_exists = Path(report.cache_path).exists()
            workspace_head = _git_output(workspace, "rev-parse", "HEAD")

        self.assertTrue(report.prepared)
        self.assertEqual(report.head_commit, base_commit)
        self.assertEqual(workspace_head, base_commit)
        self.assertEqual(workspace_text, "version = 1\n")
        self.assertTrue(cache_path_exists)
        self.assertFalse(report.cache_reused)
        self.assertIn("clone", [part for command in report.commands for part in command.argv])

    def test_prepare_benchmark_task_records_workspace_metadata_and_reuses_cache(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            source = root / "source-repo"
            source.mkdir()
            _git(source, "init")
            _git(source, "config", "user.email", "tester@example.com")
            _git(source, "config", "user.name", "Tester")
            (source / "bug.py").write_text("broken = True\n", encoding="utf-8")
            _git(source, "add", ".")
            _git(source, "commit", "-m", "initial")
            base_commit = _git_output(source, "rev-parse", "HEAD")

            task = SWEbenchTaskSpec(
                instance_id="owner__repo-2",
                repo=str(source),
                base_commit=base_commit,
                problem_statement="Fix the bug.",
            )
            provisioner = SWEbenchWorkspaceProvisioner(
                workspaces_root=root / "workspaces",
                repo_cache_root=root / "cache",
                timeout_seconds=30,
            )
            first_report = provisioner.prepare_task(task)
            (Path(first_report.workspace_root) / "dirty.txt").write_text(
                "stale\n",
                encoding="utf-8",
            )

            benchmark_task = provisioner.prepare_benchmark_task(
                task,
                verification_command="python -m pytest",
                setup_command="python -m pip install -e .",
            )
            workspace = Path(benchmark_task.workspace_root)

        self.assertEqual(benchmark_task.task_id, "owner__repo-2")
        self.assertEqual(benchmark_task.repository_commit, base_commit)
        self.assertTrue(benchmark_task.enable_git_diff_artifact)
        self.assertEqual(benchmark_task.git_diff_base_ref, base_commit)
        self.assertEqual(benchmark_task.verification_command, "python -m pytest")
        self.assertFalse((workspace / "dirty.txt").exists())
        self.assertTrue(benchmark_task.metadata["swebench_workspace"]["prepared"])
        self.assertTrue(benchmark_task.metadata["swebench_workspace"]["cache_reused"])

    def test_refuses_existing_workspace_when_overwrite_disabled(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            source = root / "source-repo"
            source.mkdir()
            _git(source, "init")
            _git(source, "config", "user.email", "tester@example.com")
            _git(source, "config", "user.name", "Tester")
            (source / "app.py").write_text("ok\n", encoding="utf-8")
            _git(source, "add", ".")
            _git(source, "commit", "-m", "initial")
            base_commit = _git_output(source, "rev-parse", "HEAD")

            task = SWEbenchTaskSpec(
                instance_id="owner__repo-3",
                repo=str(source),
                base_commit=base_commit,
                problem_statement="Fix it.",
            )
            workspaces_root = root / "workspaces"
            existing = workspaces_root / "owner__repo-3"
            existing.mkdir(parents=True)
            (existing / "keep.txt").write_text("do not delete\n", encoding="utf-8")

            provisioner = SWEbenchWorkspaceProvisioner(
                workspaces_root=workspaces_root,
                repo_cache_root=root / "cache",
                overwrite_existing=False,
                timeout_seconds=30,
            )

            with self.assertRaisesRegex(ValueError, "already exists"):
                provisioner.prepare_task(task)

            self.assertTrue((existing / "keep.txt").exists())


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
