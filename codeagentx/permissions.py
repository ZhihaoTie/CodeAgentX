"""Permission system -- distilled from Claude Code's 5-layer permission model.

Original 5 layers:
  1. Tool's own checkPermissions() -- e.g. BashTool checks for destructive commands
  2. Settings allowlist/denylist -- glob patterns like Bash(npm:*)
  3. Sandbox policy -- managed path/command/network restrictions
  4. Active permission mode -- may auto-approve or force-ask
  5. Hook overrides -- PreToolUse hooks can approve/block/modify

Mini version keeps 4 layers:
  Layer 1: Tool.check_permissions() -- each tool checks its own params
  Layer 2: WorkspacePathPolicy -- keep tool paths inside the workspace
  Layer 3: CommandRiskClassifier -- classify bash risk before execution
  Layer 4: PermissionMode -- ask / auto / plan
"""

from __future__ import annotations

from typing import Any

from .config import Config, PermissionMode
from .security import CommandRisk, CommandRiskClassifier, WorkspacePathPolicy
from .tools.base import Tool, ToolResult


FILE_PATH_TOOLS = {"read_file", "write_file", "edit_file", "grep"}
DIRECTORY_PATH_TOOLS = {"ast_context", "glob"}
SIDE_EFFECT_TOOLS = {"bash", "write_file", "edit_file"}


class PermissionDenied(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class PermissionGate:
    """Two-layer permission gate before tool execution."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.path_policy = WorkspacePathPolicy(
            config.workspace_root,
            enabled=config.enforce_workspace_paths,
        )
        self.command_classifier = CommandRiskClassifier(
            allowed_prefixes=config.allowed_commands,
            denied_patterns=config.denied_patterns,
        )

    def check(self, tool: Tool, params: dict[str, Any]) -> ToolResult | None:
        """Run the permission gauntlet. Returns a ToolResult if denied, None if allowed."""

        # Layer 1: tool-level self-check
        if tool.name == "bash":
            self._annotate_command_risk(params)

        denial = tool.check_permissions(params)
        if denial is not None:
            return ToolResult(output=f"Permission denied: {denial}", is_error=True)

        # Layer 2: workspace path policy
        path_denial = self._check_workspace_paths(tool.name, params)
        if path_denial is not None:
            return path_denial

        # Layer 3: command risk policy
        command_denial = self._check_command_risk(tool.name, params)
        if command_denial is not None:
            return command_denial

        # Layer 4: mode-based check
        mode = self.config.permission_mode

        if mode == PermissionMode.PLAN:
            if tool.name in SIDE_EFFECT_TOOLS:
                return ToolResult(
                    output=f"Permission denied: '{tool.name}' is blocked in plan (read-only) mode.",
                    is_error=True,
                )

        if mode == PermissionMode.ASK:
            if tool.name in ("write_file", "edit_file"):
                if not self._ask_user(tool.name, params):
                    return ToolResult(output="Permission denied: user rejected.", is_error=True)
            elif tool.name == "bash":
                risk = _permission_metadata(params).get("command", {}).get("risk")
                if risk != CommandRisk.SAFE.value:
                    if not self._ask_user(tool.name, params):
                        return ToolResult(output="Permission denied: user rejected.", is_error=True)

        # AUTO mode: allow everything that passed layer 1
        return None

    def _is_safe_command(self, command: str) -> bool:
        return self.command_classifier.classify(command).risk == CommandRisk.SAFE

    def _annotate_command_risk(self, params: dict[str, Any]) -> None:
        command = str(params.get("command", ""))
        classification = self.command_classifier.classify(command)
        _permission_metadata(params)["command"] = classification.to_dict()

    def _check_command_risk(self, tool_name: str, params: dict[str, Any]) -> ToolResult | None:
        if tool_name != "bash":
            return None

        risk = _permission_metadata(params).get("command", {}).get("risk")
        if risk == CommandRisk.DANGEROUS.value:
            reason = _permission_metadata(params).get("command", {}).get("reason", "")
            pattern = _permission_metadata(params).get("command", {}).get("matched_pattern", "")
            message = "Permission denied: bash command is classified as dangerous"
            if pattern:
                message += f" (matched: {pattern})"
            if reason:
                message += f": {reason}"
            return ToolResult(output=message, is_error=True)

        return None

    def _check_workspace_paths(self, tool_name: str, params: dict[str, Any]) -> ToolResult | None:
        if tool_name in FILE_PATH_TOOLS:
            raw_path = params.get("path", ".")
            result = self.path_policy.check_path(raw_path)
            if not result.allowed:
                return ToolResult(output=f"Permission denied: {result.reason}", is_error=True)
            params["path"] = str(result.path)
            _permission_metadata(params)["workspace_path"] = {
                "field": "path",
                "normalized_path": str(result.path),
                "root": str(self.path_policy.root),
            }

            if tool_name in ("write_file", "edit_file"):
                backup = self.path_policy.check_path(self.config.patch_backup_dir)
                if not backup.allowed:
                    return ToolResult(output=f"Permission denied: {backup.reason}", is_error=True)
                params["backup_dir"] = str(backup.path)
                _permission_metadata(params)["patch_backup"] = {
                    "backup_dir": str(backup.path),
                }

        if tool_name in DIRECTORY_PATH_TOOLS:
            raw_directory = params.get("directory", ".")
            result = self.path_policy.check_path(raw_directory, must_be_dir=True)
            if not result.allowed:
                return ToolResult(output=f"Permission denied: {result.reason}", is_error=True)
            params["directory"] = str(result.path)
            _permission_metadata(params)["workspace_path"] = {
                "field": "directory",
                "normalized_path": str(result.path),
                "root": str(self.path_policy.root),
            }

        if tool_name == "bash":
            raw_cwd = params.get("cwd")
            if raw_cwd is None or str(raw_cwd).strip() == "":
                raw_cwd = self.path_policy.root
            result = self.path_policy.check_path(raw_cwd, must_be_dir=True)
            if not result.allowed:
                return ToolResult(output=f"Permission denied: {result.reason}", is_error=True)
            params["cwd"] = str(result.path)
            _permission_metadata(params)["workspace_path"] = {
                "field": "cwd",
                "normalized_path": str(result.path),
                "root": str(self.path_policy.root),
            }

        return None

    @staticmethod
    def _ask_user(tool_name: str, params: dict[str, Any]) -> bool:
        detail = ""
        if tool_name == "bash":
            detail = params.get("command", "")
        elif tool_name in ("write_file", "edit_file"):
            detail = params.get("path", "")
        prompt = f"\n[Permission] Allow '{tool_name}'"
        if detail:
            prompt += f": {detail}"
        risk = _permission_metadata(params).get("command", {}).get("risk", "")
        if risk:
            prompt += f" [risk: {risk}]"
        prompt += "? [y/N] "
        try:
            answer = input(prompt).strip().lower()
            return answer in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            return False


def _permission_metadata(params: dict[str, Any]) -> dict[str, Any]:
    metadata = params.setdefault("_permission", {})
    if isinstance(metadata, dict):
        return metadata
    params["_permission"] = {}
    return params["_permission"]
