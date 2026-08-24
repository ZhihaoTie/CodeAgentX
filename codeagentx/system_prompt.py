"""System prompt builder for CodeAgent-X.

Original: merges system prompt from defaults, CLAUDE.md, memory files, tool definitions,
permission mode instructions, and hook-injected context.

Current version: single template with tool list, permission mode, and optional CLAUDE.md.
"""

from __future__ import annotations

from .context import load_project_instructions
from .tools.base import ToolRegistry

SYSTEM_PROMPT_TEMPLATE = """\
You are CodeAgent-X, an autonomous software engineering agent that operates in the terminal.

You have access to the following tools to help the user with software engineering tasks:
{tool_list}

## Operating Rules

1. Always read a file before editing it.
2. Use tools to accomplish tasks -- don't just describe what to do.
3. When running bash commands, prefer non-destructive read operations.
4. For file edits, provide enough context in old_string to uniquely match.
5. Treat every tool result as environment feedback and use it to decide the next step.
6. Be concise and direct in your responses.

## Current Permission Mode: {permission_mode}
{mode_description}

{runtime_context}

{project_instructions}"""

MODE_DESCRIPTIONS = {
    "ask": "In ASK mode, potentially dangerous operations will require user confirmation.",
    "auto": "In AUTO mode, all operations are auto-approved (use with caution).",
    "plan": "In PLAN mode, only read-only operations are allowed. Write operations are blocked.",
}


def build_system_prompt(
    registry: ToolRegistry,
    permission_mode: str = "ask",
    project_dir: str | None = None,
    workspace_root: str | None = None,
    verification_command: str | None = None,
) -> str:
    tool_list = "\n".join(
        f"- **{t.name}**: {t.description}"
        for t in registry.all_tools()
    )

    instructions = load_project_instructions(project_dir)
    project_section = ""
    if instructions:
        project_section = f"## Project Instructions (from CLAUDE.md)\n\n{instructions}"

    runtime_context = _runtime_context_section(
        workspace_root=workspace_root,
        verification_command=verification_command,
    )

    return SYSTEM_PROMPT_TEMPLATE.format(
        tool_list=tool_list,
        permission_mode=permission_mode.upper(),
        mode_description=MODE_DESCRIPTIONS.get(permission_mode, ""),
        runtime_context=runtime_context,
        project_instructions=project_section,
    ).strip()


def _runtime_context_section(
    *,
    workspace_root: str | None,
    verification_command: str | None,
) -> str:
    lines: list[str] = []
    if workspace_root:
        lines.extend([
            "## Runtime Context",
            "",
            f"- Workspace root: `{workspace_root}`",
            "- Bash commands already run from the workspace root when cwd is omitted.",
            "- Prefer relative paths inside the workspace; avoid redundant absolute `cd` commands.",
            "- Avoid dependency installation or package-manager commands unless task evidence requires them.",
        ])
    if verification_command:
        if not lines:
            lines.extend(["## Runtime Context", ""])
        lines.append(f"- Configured verification command: `{verification_command}`")
        lines.append("- Prefer this command for final verification before giving your final response.")
    return "\n".join(lines)
