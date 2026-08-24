from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from codeagentx.evaluation import collect_git_diff


@unittest.skipUnless(shutil.which("git"), "git executable is required")
class GitDiffCollectorTests(unittest.TestCase):
    def test_collects_modified_deleted_and_untracked_files(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            _git(root, "init")
            _git(root, "config", "user.email", "tester@example.com")
            _git(root, "config", "user.name", "Tester")
            (root / "app.py").write_text("print('old')\n", encoding="utf-8")
            (root / "gone.py").write_text("remove me\n", encoding="utf-8")
            _git(root, "add", ".")
            _git(root, "commit", "-m", "initial")

            (root / "app.py").write_text("print('new')\n", encoding="utf-8")
            (root / "gone.py").unlink()
            (root / "new.py").write_text("created = True\n", encoding="utf-8")

            report = collect_git_diff(root)

        self.assertFalse(report.is_clean)
        self.assertTrue(report.is_git_repository)
        self.assertIn("app.py", report.changed_files)
        self.assertIn("gone.py", report.deleted_files)
        self.assertIn("new.py", report.untracked_files)
        self.assertIn("-print('old')", report.patch_diff)
        self.assertIn("+print('new')", report.patch_diff)
        self.assertIn("diff --git a/new.py b/new.py", report.patch_diff)
        self.assertGreater(report.patch_bytes, 0)
        self.assertIsNone(report.error)

    def test_reports_non_git_workspace(self):
        with tempfile.TemporaryDirectory() as tempdir:
            report = collect_git_diff(tempdir)

        self.assertFalse(report.is_git_repository)
        self.assertFalse(report.is_clean)
        self.assertIsNotNone(report.error)


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
