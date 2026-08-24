"""Tests for patch transaction based file writes."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codeagentx.agent import AgentAction, ToolExecutor
from codeagentx.config import Config, PermissionMode
from codeagentx.patching import PatchApplyResult, PatchOperation, PatchTransaction
from codeagentx.patching import rollback_applied_patches
from codeagentx.tools.base import ToolRegistry
from codeagentx.tools.file_edit import FileEditTool
from codeagentx.tools.file_write import FileWriteTool


class TestPatchTransaction(unittest.TestCase):
    def test_write_new_file_generates_diff_and_can_rollback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "new.txt"
            transaction = PatchTransaction.for_write(path, "hello\n")

            diff = transaction.preview_diff()
            result = transaction.apply(backup_root=Path(tmpdir) / "backups")
            rollback = transaction.rollback(result)

            self.assertIn("+hello", diff)
            self.assertEqual(result.operation, PatchOperation.WRITE)
            self.assertFalse(result.before_exists)
            self.assertTrue(rollback.restored)
            self.assertFalse(path.exists())

    def test_edit_existing_file_creates_backup_and_can_rollback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "app.py"
            path.write_text("before\n")
            transaction = PatchTransaction.for_edit(
                path,
                before_content="before\n",
                after_content="after\n",
            )

            result = transaction.apply(backup_root=Path(tmpdir) / "backups")
            rollback = transaction.rollback(result)

            self.assertEqual(path.read_text(), "before\n")
            self.assertTrue(Path(result.backup_path).exists())
            self.assertIn("-before", result.diff)
            self.assertIn("+after", result.diff)
            self.assertTrue(rollback.restored)

    def test_can_rollback_from_recorded_patch_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "app.py"
            path.write_text("before\n")
            transaction = PatchTransaction.for_write(path, "after\n")

            result = transaction.apply(backup_root=Path(tmpdir) / "backups")
            reconstructed = PatchApplyResult.from_dict(result.to_dict())
            rollback = PatchTransaction.rollback_applied(reconstructed)

            self.assertTrue(rollback.restored)
            self.assertEqual(path.read_text(), "before\n")

    def test_rolls_back_multiple_patches_in_reverse_order(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "app.py"
            first = PatchTransaction.for_write(path, "one\n")
            first_result = first.apply(backup_root=Path(tmpdir) / "backups")
            second = PatchTransaction.for_edit(
                path,
                before_content="one\n",
                after_content="two\n",
            )
            second_result = second.apply(backup_root=Path(tmpdir) / "backups")

            report = rollback_applied_patches([
                first_result.to_dict(),
                second_result.to_dict(),
            ])

            self.assertEqual(report.status, "passed")
            self.assertEqual(report.attempted, 2)
            self.assertEqual(report.restored, 2)
            self.assertFalse(path.exists())


class TestPatchFileTools(unittest.TestCase):
    def test_write_file_returns_patch_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "out.txt"
            tool = FileWriteTool()

            result = tool.execute({
                "path": str(path),
                "content": "hello\n",
                "backup_dir": str(Path(tmpdir) / "backups"),
            })

        self.assertFalse(result.is_error)
        self.assertIn("Patch transaction:", result.output)
        self.assertEqual(result.metadata["patch"]["operation"], "write_file")
        self.assertIn("+hello", result.metadata["patch"]["diff"])

    def test_edit_file_returns_patch_metadata_and_backup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "app.py"
            path.write_text("x = 1\n")
            tool = FileEditTool()

            result = tool.execute({
                "path": str(path),
                "old_string": "x = 1",
                "new_string": "x = 2",
                "backup_dir": str(Path(tmpdir) / "backups"),
            })

            backup_path = Path(result.metadata["patch"]["backup_path"])

            self.assertFalse(result.is_error)
            self.assertIn("Patch transaction:", result.output)
            self.assertEqual(result.metadata["patch"]["operation"], "edit_file")
            self.assertTrue(backup_path.exists())
            self.assertIn("-x = 1", result.metadata["patch"]["diff"])
            self.assertIn("+x = 2", result.metadata["patch"]["diff"])


class TestPatchExecutorIntegration(unittest.TestCase):
    def test_executor_records_patch_and_permission_metadata(self):
        with tempfile.TemporaryDirectory() as workspace:
            registry = ToolRegistry()
            registry.register(FileWriteTool())
            executor = ToolExecutor(
                registry=registry,
                config=Config(
                    permission_mode=PermissionMode.AUTO,
                    workspace_root=workspace,
                ),
            )

            observation = executor.execute(AgentAction(
                tool_name="write_file",
                tool_input={"path": "notes.txt", "content": "hello\n"},
            ))

            written = Path(workspace) / "notes.txt"

            self.assertFalse(observation.is_error)
            self.assertEqual(written.read_text(), "hello\n")
            self.assertEqual(observation.metadata["patch"]["operation"], "write_file")
            self.assertIn("patch_backup", observation.metadata["permission"])
            self.assertIn("workspace_path", observation.metadata["permission"])


if __name__ == "__main__":
    unittest.main()
