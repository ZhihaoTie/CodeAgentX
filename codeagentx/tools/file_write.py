"""FileWrite tool -- write content via a patch transaction."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from codeagentx.patching import PatchApplyError, PatchTransaction

from .base import Tool, ToolResult


class FileWriteTool(Tool):
    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "Write content to a file. Creates parent directories if they don't exist. Overwrites if the file already exists."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute or relative path to the file."},
                "content": {"type": "string", "description": "The content to write."},
            },
            "required": ["path", "content"],
        }

    def execute(self, params: dict[str, Any]) -> ToolResult:
        filepath = Path(params["path"]).expanduser()
        content = params.get("content", "")
        backup_dir = params.get("backup_dir")
        try:
            transaction = PatchTransaction.for_write(filepath, content)
            result = transaction.apply(backup_root=backup_dir)
            return ToolResult(
                output=_format_patch_output(
                    summary=f"Wrote {len(content)} chars to {filepath}",
                    diff=result.diff,
                    diff_truncated=result.diff_truncated,
                    transaction_id=result.transaction_id,
                    backup_path=result.backup_path,
                ),
                metadata={"patch": result.to_dict()},
            )
        except (PatchApplyError, OSError, UnicodeError) as exc:
            return ToolResult(output=f"Error writing file: {exc}", is_error=True)


def _format_patch_output(
    *,
    summary: str,
    diff: str,
    diff_truncated: bool,
    transaction_id: str,
    backup_path: str,
) -> str:
    lines = [
        summary,
        f"Patch transaction: {transaction_id}",
    ]
    if backup_path:
        lines.append(f"Backup: {backup_path}")
    if diff:
        lines.append("Diff:")
        lines.append(diff)
        if diff_truncated:
            lines.append("(diff truncated)")
    else:
        lines.append("Diff: (no content changes)")
    return "\n".join(lines)
