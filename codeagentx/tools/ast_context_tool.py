"""AST context tool for semantic Python repository lookup."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from codeagentx.context_engine import AstContextManager, SUPPORTED_SOURCE_SUFFIXES, SymbolKind

from .base import Tool, ToolResult


class AstContextTool(Tool):
    @property
    def name(self) -> str:
        return "ast_context"

    @property
    def description(self) -> str:
        return (
            "Build a multi-language code index and retrieve relevant classes, "
            "functions, methods, interfaces, imports, and calls for a query."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Symbol, method, import, call, or path fragment to retrieve.",
                },
                "directory": {
                    "type": "string",
                    "description": "Directory to index (default: current workspace directory).",
                },
                "kind": {
                    "type": "string",
                    "enum": [kind.value for kind in SymbolKind],
                    "description": "Optional symbol kind filter.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of symbol matches to return.",
                },
            },
            "required": ["query"],
        }

    def check_permissions(self, params: dict[str, Any]) -> str | None:
        limit = params.get("limit", 8)
        try:
            if int(limit) <= 0:
                return "limit must be positive"
        except (TypeError, ValueError):
            return "limit must be an integer"

        kind = params.get("kind")
        if kind not in (None, ""):
            try:
                SymbolKind(str(kind))
            except ValueError:
                return f"unsupported kind: {kind}"
        return None

    def execute(self, params: dict[str, Any]) -> ToolResult:
        query = str(params.get("query", "")).strip()
        if not query:
            return ToolResult(output="Error: query must not be empty", is_error=True)

        directory = Path(params.get("directory", ".")).expanduser().resolve()
        if not directory.exists():
            return ToolResult(output=f"Error: directory not found: {directory}", is_error=True)
        if not directory.is_dir() and directory.suffix.lower() not in SUPPORTED_SOURCE_SUFFIXES:
            return ToolResult(
                output=f"Error: expected a directory or supported source file: {directory}",
                is_error=True,
            )

        limit = int(params.get("limit", 8))
        kind = params.get("kind")

        try:
            manager = AstContextManager(directory)
            output = manager.context_block(query, kind=kind, limit=limit)
            metadata = {"ast_context": manager.metadata_for_query(query, kind=kind, limit=limit)}
            return ToolResult(output=output, metadata=metadata)
        except Exception as exc:
            return ToolResult(
                output=f"Error building AST context: {exc.__class__.__name__}: {exc}",
                is_error=True,
            )
