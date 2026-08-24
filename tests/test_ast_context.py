"""Tests for AST context indexing and retrieval."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codeagentx.agent import AgentAction, ToolExecutor
from codeagentx.config import Config, PermissionMode
from codeagentx.context_engine import AstContextManager, SymbolKind
from codeagentx.tools.ast_context_tool import AstContextTool
from codeagentx.tools.base import ToolRegistry


class TestAstContextManager(unittest.TestCase):
    def test_indexes_python_symbols_imports_and_calls(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package = root / "pkg"
            package.mkdir()
            (package / "service.py").write_text(
                "\n".join([
                    "import os",
                    "from .repo import load_user as load",
                    "",
                    "class UserService(BaseService):",
                    "    \"\"\"Coordinates user reads.\"\"\"",
                    "",
                    "    def get_user(self, user_id):",
                    "        return load(user_id)",
                    "",
                    "async def build_service():",
                    "    return UserService()",
                    "",
                ]),
                encoding="utf-8",
            )
            (package / "broken.py").write_text("def broken(:\n", encoding="utf-8")
            (root / ".codeagentx").mkdir()
            (root / ".codeagentx" / "ignored.py").write_text(
                "class Ignored: pass\n",
                encoding="utf-8",
            )

            manager = AstContextManager(root)
            index = manager.index
            class_matches = manager.retrieve("UserService", kind=SymbolKind.CLASS)
            method_matches = manager.retrieve("get_user", kind="method")
            context = manager.context_block("load_user")

        self.assertEqual(index.file_count, 2)
        self.assertEqual(index.parse_error_count, 1)
        self.assertGreaterEqual(index.symbol_count, 3)
        self.assertEqual(class_matches[0].symbol.qualified_name, "UserService")
        self.assertEqual(class_matches[0].symbol.bases, ["BaseService"])
        self.assertEqual(method_matches[0].symbol.qualified_name, "UserService.get_user")
        self.assertIn("pkg/service.py:2 .repo.load_user as load", context)
        self.assertNotIn("Ignored", context)

    def test_scores_symbols_by_calls(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "worker.py").write_text(
                "\n".join([
                    "def helper():",
                    "    pass",
                    "",
                    "def orchestrate():",
                    "    helper()",
                    "",
                ]),
                encoding="utf-8",
            )

            matches = AstContextManager(root).retrieve("helper")

        names = [match.symbol.qualified_name for match in matches]
        self.assertEqual(names[0], "helper")
        self.assertIn("orchestrate", names)
        orchestrate = next(match for match in matches if match.symbol.name == "orchestrate")
        self.assertIn("calls helper", orchestrate.reasons)

    def test_indexes_javascript_and_typescript_symbols_imports_and_calls(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            src = root / "src"
            src.mkdir()
            (src / "service.ts").write_text(
                "\n".join([
                    "import { loadUser as loadUserRecord } from './repo';",
                    "import Logger from './logger';",
                    "",
                    "export interface UserRecord {",
                    "  id: string;",
                    "}",
                    "",
                    "export class UserService extends BaseService {",
                    "  async getUser(userId: string) {",
                    "    Logger.info(userId);",
                    "    return loadUserRecord(userId);",
                    "  }",
                    "}",
                    "",
                    "export function buildService() {",
                    "  return new UserService();",
                    "}",
                ]),
                encoding="utf-8",
            )
            (src / "factory.js").write_text(
                "const createUser = (name) => buildService().getUser(name);\n",
                encoding="utf-8",
            )

            manager = AstContextManager(root)
            index = manager.index
            class_matches = manager.retrieve("UserService", kind=SymbolKind.CLASS)
            method_matches = manager.retrieve("getUser", kind="method")
            interface_matches = manager.retrieve("UserRecord", kind="interface")
            context = manager.context_block("loadUserRecord")

        self.assertEqual(index.file_count, 2)
        self.assertEqual(index.language_counts["typescript"], 1)
        self.assertEqual(index.language_counts["javascript"], 1)
        self.assertEqual(class_matches[0].symbol.qualified_name, "UserService")
        self.assertEqual(class_matches[0].symbol.language, "typescript")
        self.assertEqual(class_matches[0].symbol.bases, ["BaseService"])
        self.assertEqual(method_matches[0].symbol.qualified_name, "UserService.getUser")
        self.assertEqual(interface_matches[0].symbol.kind, SymbolKind.INTERFACE)
        self.assertIn("src/service.ts:1 ./repo.loadUser as loadUserRecord", context)
        self.assertIn("UserService.getUser -> loadUserRecord", context)


class TestAstContextTool(unittest.TestCase):
    def test_tool_returns_context_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "service.py").write_text(
                "class UserService:\n"
                "    def get_user(self):\n"
                "        return None\n",
                encoding="utf-8",
            )
            tool = AstContextTool()

            result = tool.execute({
                "directory": tmpdir,
                "query": "UserService",
                "limit": 3,
            })

        self.assertFalse(result.is_error)
        self.assertIn("AST Context for query", result.output)
        self.assertIn("class UserService", result.output)
        self.assertEqual(result.metadata["ast_context"]["symbol_count"], 2)
        self.assertEqual(
            result.metadata["ast_context"]["matches"][0]["symbol"]["qualified_name"],
            "UserService",
        )

    def test_tool_accepts_typescript_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = root / "service.ts"
            path.write_text(
                "export class UserService { getUser() { return loadUser(); } }\n",
                encoding="utf-8",
            )
            tool = AstContextTool()

            result = tool.execute({
                "directory": str(path),
                "query": "UserService",
                "limit": 3,
            })

        self.assertFalse(result.is_error)
        self.assertIn("class UserService", result.output)
        self.assertEqual(result.metadata["ast_context"]["language_counts"]["typescript"], 1)

    def test_executor_blocks_ast_context_outside_workspace(self):
        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as outside:
            Path(outside, "service.py").write_text("class Secret: pass\n", encoding="utf-8")
            registry = ToolRegistry()
            registry.register(AstContextTool())
            executor = ToolExecutor(
                registry=registry,
                config=Config(
                    permission_mode=PermissionMode.AUTO,
                    workspace_root=workspace,
                ),
            )

            observation = executor.execute(AgentAction(
                tool_name="ast_context",
                tool_input={"directory": outside, "query": "Secret"},
            ))

        self.assertTrue(observation.is_error)
        self.assertIn("outside workspace", observation.output)


if __name__ == "__main__":
    unittest.main()
