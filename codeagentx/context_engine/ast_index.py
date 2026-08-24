"""Python AST repository indexing and retrieval."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


DEFAULT_EXCLUDED_DIRS = {
    ".git",
    ".codeagentx",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
    ".venv",
}


class SymbolKind(Enum):
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    INTERFACE = "interface"


SUPPORTED_SOURCE_SUFFIXES = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
}


@dataclass(frozen=True)
class SourceLocation:
    path: str
    line: int
    end_line: int
    column: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "line": self.line,
            "end_line": self.end_line,
            "column": self.column,
        }


@dataclass(frozen=True)
class SymbolRecord:
    name: str
    qualified_name: str
    kind: SymbolKind
    location: SourceLocation
    language: str = "python"
    signature: str = ""
    parent: str = ""
    docstring: str = ""
    decorators: list[str] = field(default_factory=list)
    bases: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "qualified_name": self.qualified_name,
            "kind": self.kind.value,
            "location": self.location.to_dict(),
            "language": self.language,
            "signature": self.signature,
            "parent": self.parent,
            "docstring": self.docstring,
            "decorators": list(self.decorators),
            "bases": list(self.bases),
        }


@dataclass(frozen=True)
class ImportRecord:
    path: str
    line: int
    module: str
    name: str = ""
    alias: str = ""

    @property
    def display_name(self) -> str:
        if self.name:
            value = f"{self.module}.{self.name}" if self.module else self.name
        else:
            value = self.module
        if self.alias:
            value += f" as {self.alias}"
        return value

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "line": self.line,
            "module": self.module,
            "name": self.name,
            "alias": self.alias,
            "display_name": self.display_name,
        }


@dataclass(frozen=True)
class CallRecord:
    path: str
    line: int
    name: str
    enclosing_symbol: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "line": self.line,
            "name": self.name,
            "enclosing_symbol": self.enclosing_symbol,
        }


@dataclass(frozen=True)
class FileIndex:
    path: str
    language: str = "python"
    symbols: list[SymbolRecord] = field(default_factory=list)
    imports: list[ImportRecord] = field(default_factory=list)
    calls: list[CallRecord] = field(default_factory=list)
    parse_error: str = ""

    @property
    def parsed(self) -> bool:
        return not self.parse_error

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "language": self.language,
            "symbols": [symbol.to_dict() for symbol in self.symbols],
            "imports": [item.to_dict() for item in self.imports],
            "calls": [call.to_dict() for call in self.calls],
            "parse_error": self.parse_error,
        }


@dataclass(frozen=True)
class SymbolSearchResult:
    symbol: SymbolRecord
    score: int
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol.to_dict(),
            "score": self.score,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class RepositoryAstIndex:
    root: str
    files: list[FileIndex]
    indexed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def file_count(self) -> int:
        return len(self.files)

    @property
    def symbol_count(self) -> int:
        return sum(len(file.symbols) for file in self.files)

    @property
    def import_count(self) -> int:
        return sum(len(file.imports) for file in self.files)

    @property
    def call_count(self) -> int:
        return sum(len(file.calls) for file in self.files)

    @property
    def parse_error_count(self) -> int:
        return sum(1 for file in self.files if file.parse_error)

    @property
    def language_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for file in self.files:
            counts[file.language] = counts.get(file.language, 0) + 1
        return counts

    def all_symbols(self) -> list[SymbolRecord]:
        return [symbol for file in self.files for symbol in file.symbols]

    def find_symbols(
        self,
        query: str,
        *,
        kind: str | SymbolKind | None = None,
        limit: int = 10,
    ) -> list[SymbolSearchResult]:
        normalized = query.strip().lower()
        if not normalized:
            return []
        kind_filter = _coerce_kind(kind)
        calls_by_symbol = self._calls_by_enclosing_symbol()
        results: list[SymbolSearchResult] = []

        for symbol in self.all_symbols():
            if kind_filter is not None and symbol.kind != kind_filter:
                continue
            score, reasons = _score_symbol(symbol, normalized, calls_by_symbol)
            if score > 0:
                results.append(SymbolSearchResult(symbol=symbol, score=score, reasons=reasons))

        return sorted(
            results,
            key=lambda item: (-item.score, item.symbol.location.path, item.symbol.location.line),
        )[:limit]

    def find_imports(self, query: str, *, limit: int = 10) -> list[ImportRecord]:
        normalized = query.strip().lower()
        if not normalized:
            return []
        imports = [
            item
            for file in self.files
            for item in file.imports
            if normalized in item.display_name.lower()
        ]
        return sorted(imports, key=lambda item: (item.path, item.line))[:limit]

    def find_calls(self, query: str, *, limit: int = 10) -> list[CallRecord]:
        normalized = query.strip().lower()
        if not normalized:
            return []
        calls = [
            call
            for file in self.files
            for call in file.calls
            if normalized in call.name.lower()
        ]
        return sorted(calls, key=lambda item: (item.path, item.line, item.name))[:limit]

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "indexed_at": self.indexed_at,
            "file_count": self.file_count,
            "symbol_count": self.symbol_count,
            "import_count": self.import_count,
            "call_count": self.call_count,
            "parse_error_count": self.parse_error_count,
            "language_counts": dict(self.language_counts),
            "files": [file.to_dict() for file in self.files],
        }

    def _calls_by_enclosing_symbol(self) -> dict[str, list[CallRecord]]:
        grouped: dict[str, list[CallRecord]] = {}
        for file in self.files:
            for call in file.calls:
                grouped.setdefault(call.enclosing_symbol, []).append(call)
        return grouped


class AstContextManager:
    """Builds and queries a repository-level multi-language code index."""

    def __init__(
        self,
        root: str | Path,
        *,
        excluded_dirs: set[str] | None = None,
        max_files: int = 1000,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.excluded_dirs = excluded_dirs or set(DEFAULT_EXCLUDED_DIRS)
        self.max_files = max_files
        self._index: RepositoryAstIndex | None = None

    @property
    def index(self) -> RepositoryAstIndex:
        if self._index is None:
            self._index = self.build_index()
        return self._index

    def build_index(self) -> RepositoryAstIndex:
        files: list[FileIndex] = []
        for path in self._iter_source_files():
            files.append(index_source_file(self.root, path))
        return RepositoryAstIndex(root=str(self.root), files=files)

    def retrieve(
        self,
        query: str,
        *,
        kind: str | SymbolKind | None = None,
        limit: int = 8,
    ) -> list[SymbolSearchResult]:
        return self.index.find_symbols(query, kind=kind, limit=limit)

    def context_block(
        self,
        query: str,
        *,
        kind: str | SymbolKind | None = None,
        limit: int = 8,
    ) -> str:
        index = self.index
        matches = index.find_symbols(query, kind=kind, limit=limit)
        imports = index.find_imports(query, limit=min(limit, 5))
        calls = index.find_calls(query, limit=min(limit, 5))

        lines = [
            f'AST Context for query: "{query}"',
            (
                "Indexed: "
                f"{index.file_count} files, {index.symbol_count} symbols, "
                f"{index.import_count} imports, {index.call_count} calls, "
                f"{index.parse_error_count} parse errors, "
                f"languages={_format_language_counts(index.language_counts)}"
            ),
        ]

        if matches:
            lines.append("")
            lines.append("Symbols:")
            for result in matches:
                symbol = result.symbol
                location = symbol.location
                label = _symbol_label(symbol)
                reason = ", ".join(result.reasons)
                lines.append(
                    f"- {location.path}:{location.line} {label} "
                    f"[score={result.score}; {reason}]"
                )
                if symbol.docstring:
                    lines.append(f"  doc: {_first_line(symbol.docstring)}")
                if symbol.bases:
                    lines.append(f"  bases: {', '.join(symbol.bases)}")
        else:
            lines.append("")
            lines.append("Symbols: no matches")

        if imports:
            lines.append("")
            lines.append("Imports:")
            for item in imports:
                lines.append(f"- {item.path}:{item.line} {item.display_name}")

        if calls:
            lines.append("")
            lines.append("Calls:")
            for call in calls:
                owner = call.enclosing_symbol or "<module>"
                lines.append(f"- {call.path}:{call.line} {owner} -> {call.name}")

        parse_errors = [file for file in index.files if file.parse_error]
        if parse_errors:
            lines.append("")
            lines.append("Parse Errors:")
            for file in parse_errors[:5]:
                lines.append(f"- {file.path}: {file.parse_error}")

        return "\n".join(lines)

    def metadata_for_query(
        self,
        query: str,
        *,
        kind: str | SymbolKind | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        index = self.index
        return {
            "root": index.root,
            "file_count": index.file_count,
            "symbol_count": index.symbol_count,
            "import_count": index.import_count,
            "call_count": index.call_count,
            "parse_error_count": index.parse_error_count,
            "language_counts": dict(index.language_counts),
            "matches": [
                result.to_dict()
                for result in index.find_symbols(query, kind=kind, limit=limit)
            ],
            "imports": [
                item.to_dict()
                for item in index.find_imports(query, limit=min(limit, 5))
            ],
            "calls": [
                item.to_dict()
                for item in index.find_calls(query, limit=min(limit, 5))
            ],
        }

    def _iter_source_files(self) -> list[Path]:
        if self.root.is_file():
            return [self.root] if self.root.suffix.lower() in SUPPORTED_SOURCE_SUFFIXES else []

        files: list[Path] = []
        for path in sorted(self.root.rglob("*")):
            if path.suffix.lower() not in SUPPORTED_SOURCE_SUFFIXES:
                continue
            if _is_excluded(path, self.root, self.excluded_dirs):
                continue
            files.append(path)
            if len(files) >= self.max_files:
                break
        return files

    def _iter_python_files(self) -> list[Path]:
        return [
            path
            for path in self._iter_source_files()
            if path.suffix.lower() == ".py"
        ]


class PythonAstIndexer:
    """Indexes one Python source file with the standard library ast parser."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()

    def index_file(self, path: str | Path) -> FileIndex:
        file_path = Path(path).expanduser().resolve()
        relative_path = _relative_path(file_path, self.root)
        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError as exc:
            return FileIndex(
                path=relative_path,
                parse_error=f"SyntaxError line {exc.lineno}: {exc.msg}",
            )
        except OSError as exc:
            return FileIndex(path=relative_path, parse_error=f"OSError: {exc}")

        visitor = _AstCollector(relative_path)
        visitor.visit(tree)
        return FileIndex(
            path=relative_path,
            language="python",
            symbols=visitor.symbols,
            imports=visitor.imports,
            calls=visitor.calls,
        )


def index_source_file(root: str | Path, path: str | Path) -> FileIndex:
    suffix = Path(path).suffix.lower()
    language = SUPPORTED_SOURCE_SUFFIXES.get(suffix, "")
    if language == "python":
        return PythonAstIndexer(root).index_file(path)
    if language in {"javascript", "typescript"}:
        return JavaScriptTypeScriptIndexer(root, language=language).index_file(path)
    relative_path = _relative_path(Path(path).expanduser().resolve(), Path(root).expanduser().resolve())
    return FileIndex(path=relative_path, language=language or "unknown", parse_error="unsupported source type")


@dataclass(frozen=True)
class _Scope:
    qualified_name: str
    body_depth: int


class JavaScriptTypeScriptIndexer:
    """Indexes JS/TS with lightweight rules behind the same repository index API.

    The class intentionally avoids a hard dependency on tree-sitter so offline
    tests stay deterministic. Its output shape matches the Python AST indexer,
    which lets a future tree-sitter backend replace only this parser layer.
    """

    def __init__(self, root: str | Path, *, language: str) -> None:
        self.root = Path(root).expanduser().resolve()
        self.language = language

    def index_file(self, path: str | Path) -> FileIndex:
        file_path = Path(path).expanduser().resolve()
        relative_path = _relative_path(file_path, self.root)
        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return FileIndex(
                path=relative_path,
                language=self.language,
                parse_error=f"OSError: {exc}",
            )

        collector = _JavaScriptTypeScriptCollector(relative_path, self.language)
        collector.collect(source)
        return FileIndex(
            path=relative_path,
            language=self.language,
            symbols=collector.symbols,
            imports=collector.imports,
            calls=collector.calls,
        )


class _JavaScriptTypeScriptCollector:
    def __init__(self, path: str, language: str) -> None:
        self.path = path
        self.language = language
        self.symbols: list[SymbolRecord] = []
        self.imports: list[ImportRecord] = []
        self.calls: list[CallRecord] = []
        self._scopes: list[_Scope] = []
        self._classes: list[_Scope] = []
        self._brace_depth = 0

    def collect(self, source: str) -> None:
        in_block_comment = False
        for line_number, raw_line in enumerate(source.splitlines(), start=1):
            code, in_block_comment = _strip_js_comments(raw_line, in_block_comment)
            stripped = code.strip()
            if not stripped:
                self._update_scopes(code)
                continue

            self._collect_import(stripped, line_number)
            declared_names = self._collect_symbols(stripped, line_number)
            self._collect_calls(stripped, line_number, declared_names)
            self._update_scopes(code)

    @property
    def _current_scope(self) -> str:
        return self._scopes[-1].qualified_name if self._scopes else ""

    @property
    def _current_class(self) -> str:
        return self._classes[-1].qualified_name if self._classes else ""

    def _collect_import(self, stripped: str, line_number: int) -> None:
        for record in _js_import_records(stripped, path=self.path, line=line_number):
            self.imports.append(record)

    def _collect_symbols(self, stripped: str, line_number: int) -> set[str]:
        declared: set[str] = set()

        class_match = _JS_CLASS_RE.match(stripped)
        if class_match:
            name = class_match.group("name")
            parent = self._current_scope
            qualified = _qualified_name([parent] if parent else [], name)
            bases = [class_match.group("base")] if class_match.group("base") else []
            self.symbols.append(SymbolRecord(
                name=name,
                qualified_name=qualified,
                kind=SymbolKind.CLASS,
                location=SourceLocation(self.path, line_number, line_number),
                language=self.language,
                parent=parent,
                bases=bases,
            ))
            self._push_scope(qualified, stripped, class_scope=True)
            declared.add(name)

        interface_match = _TS_INTERFACE_RE.match(stripped)
        if interface_match:
            name = interface_match.group("name")
            parent = self._current_scope
            qualified = _qualified_name([parent] if parent else [], name)
            self.symbols.append(SymbolRecord(
                name=name,
                qualified_name=qualified,
                kind=SymbolKind.INTERFACE,
                location=SourceLocation(self.path, line_number, line_number),
                language=self.language,
                parent=parent,
            ))
            self._push_scope(qualified, stripped, class_scope=False)
            declared.add(name)

        function_match = _JS_FUNCTION_RE.match(stripped)
        if function_match and not self._current_class:
            name = function_match.group("name")
            self._append_function_symbol(
                name=name,
                params=function_match.group("params"),
                line_number=line_number,
                is_async=bool(function_match.group("async")),
            )
            self._push_scope(self._qualified(name), stripped, class_scope=False)
            declared.add(name)

        variable_function = _JS_VARIABLE_FUNCTION_RE.match(stripped)
        if variable_function and not self._current_class:
            name = variable_function.group("name")
            params = (
                variable_function.group("function_params")
                or variable_function.group("arrow_params")
                or variable_function.group("single_param")
                or ""
            )
            self._append_function_symbol(
                name=name,
                params=params,
                line_number=line_number,
                is_async=bool(variable_function.group("async")),
            )
            self._push_scope(self._qualified(name), stripped, class_scope=False)
            declared.add(name)

        method_match = _JS_METHOD_RE.match(stripped)
        if method_match and self._current_class and method_match.group("name") not in _JS_CONTROL_WORDS:
            name = method_match.group("name")
            qualified = _qualified_name([self._current_class], name)
            self.symbols.append(SymbolRecord(
                name=name,
                qualified_name=qualified,
                kind=SymbolKind.METHOD,
                location=SourceLocation(self.path, line_number, line_number),
                language=self.language,
                signature=_js_signature(name, method_match.group("params"), bool(method_match.group("async"))),
                parent=self._current_class,
            ))
            self._push_scope(qualified, stripped, class_scope=False)
            declared.add(name)

        return declared

    def _append_function_symbol(
        self,
        *,
        name: str,
        params: str,
        line_number: int,
        is_async: bool,
    ) -> None:
        parent = self._current_scope
        qualified = self._qualified(name)
        self.symbols.append(SymbolRecord(
            name=name,
            qualified_name=qualified,
            kind=SymbolKind.FUNCTION,
            location=SourceLocation(self.path, line_number, line_number),
            language=self.language,
            signature=_js_signature(name, params, is_async),
            parent=parent,
        ))

    def _collect_calls(self, stripped: str, line_number: int, declared_names: set[str]) -> None:
        for name in _js_call_names(stripped):
            if name in declared_names or name in _JS_CONTROL_WORDS:
                continue
            self.calls.append(CallRecord(
                path=self.path,
                line=line_number,
                name=name,
                enclosing_symbol=self._current_scope,
            ))

    def _qualified(self, name: str) -> str:
        parent = self._current_scope
        return _qualified_name([parent] if parent else [], name)

    def _push_scope(self, qualified_name: str, stripped: str, *, class_scope: bool) -> None:
        body_depth = self._body_depth_after_declaration(stripped)
        scope = _Scope(qualified_name=qualified_name, body_depth=body_depth)
        self._scopes.append(scope)
        if class_scope:
            self._classes.append(scope)

    def _body_depth_after_declaration(self, stripped: str) -> int:
        opens = stripped.count("{")
        closes = stripped.count("}")
        if opens <= closes:
            return self._brace_depth + 1
        return self._brace_depth + opens - closes

    def _update_scopes(self, code: str) -> None:
        self._brace_depth += code.count("{") - code.count("}")
        while self._scopes and self._brace_depth < self._scopes[-1].body_depth:
            scope = self._scopes.pop()
            if self._classes and self._classes[-1] == scope:
                self._classes.pop()


_IDENT = r"[A-Za-z_$][A-Za-z0-9_$]*"
_JS_CLASS_RE = re.compile(
    rf"^(?:export\s+)?(?:default\s+)?class\s+(?P<name>{_IDENT})"
    rf"(?:\s+extends\s+(?P<base>{_IDENT}(?:\.{_IDENT})?))?"
)
_TS_INTERFACE_RE = re.compile(
    rf"^(?:export\s+)?interface\s+(?P<name>{_IDENT})"
)
_JS_FUNCTION_RE = re.compile(
    rf"^(?:export\s+)?(?:default\s+)?(?P<async>async\s+)?function\s+"
    rf"(?P<name>{_IDENT})\s*\((?P<params>[^)]*)\)"
)
_JS_VARIABLE_FUNCTION_RE = re.compile(
    rf"^(?:export\s+)?(?:const|let|var)\s+(?P<name>{_IDENT})\s*=\s*"
    rf"(?:(?P<async>async)\s*)?"
    rf"(?:function\s*\((?P<function_params>[^)]*)\)|"
    rf"\((?P<arrow_params>[^)]*)\)\s*=>|"
    rf"(?P<single_param>{_IDENT})\s*=>)"
)
_JS_METHOD_RE = re.compile(
    rf"^(?:(?:public|private|protected|readonly|static|get|set)\s+)*"
    rf"(?P<async>async\s+)?(?P<name>{_IDENT})\s*\((?P<params>[^)]*)\)"
)
_JS_IMPORT_FROM_RE = re.compile(
    r"^import\s+(?P<names>.+?)\s+from\s+['\"](?P<module>[^'\"]+)['\"]"
)
_JS_IMPORT_SIDE_EFFECT_RE = re.compile(
    r"^import\s+['\"](?P<module>[^'\"]+)['\"]"
)
_JS_REQUIRE_RE = re.compile(
    rf"^(?:const|let|var)\s+(?P<alias>{_IDENT}|\{{[^}}]+\}})\s*=\s*require\(['\"](?P<module>[^'\"]+)['\"]\)"
)
_JS_CALL_RE = re.compile(
    rf"(?<!function\s)(?P<name>{_IDENT}(?:\.{_IDENT})*)\s*\("
)
_JS_CONTROL_WORDS = {
    "catch",
    "constructor",
    "for",
    "function",
    "if",
    "import",
    "return",
    "switch",
    "while",
}


def _strip_js_comments(line: str, in_block_comment: bool) -> tuple[str, bool]:
    result: list[str] = []
    index = 0
    while index < len(line):
        if in_block_comment:
            end = line.find("*/", index)
            if end < 0:
                return "".join(result), True
            index = end + 2
            in_block_comment = False
            continue
        if line.startswith("//", index):
            break
        if line.startswith("/*", index):
            in_block_comment = True
            index += 2
            continue
        result.append(line[index])
        index += 1
    return "".join(result), in_block_comment


def _js_import_records(stripped: str, *, path: str, line: int) -> list[ImportRecord]:
    records: list[ImportRecord] = []
    from_match = _JS_IMPORT_FROM_RE.match(stripped)
    if from_match:
        module = from_match.group("module")
        for name, alias in _split_js_import_names(from_match.group("names")):
            records.append(ImportRecord(
                path=path,
                line=line,
                module=module,
                name=name,
                alias=alias,
            ))
        return records

    side_effect = _JS_IMPORT_SIDE_EFFECT_RE.match(stripped)
    if side_effect:
        return [ImportRecord(path=path, line=line, module=side_effect.group("module"))]

    require_match = _JS_REQUIRE_RE.match(stripped)
    if require_match:
        alias = require_match.group("alias").strip()
        return [ImportRecord(path=path, line=line, module=require_match.group("module"), alias=alias)]

    return []


def _split_js_import_names(value: str) -> list[tuple[str, str]]:
    names = value.strip()
    if names.startswith("{") and names.endswith("}"):
        result: list[tuple[str, str]] = []
        for part in names[1:-1].split(","):
            item = part.strip()
            if not item:
                continue
            pieces = re.split(r"\s+as\s+", item, maxsplit=1)
            name = pieces[0].strip()
            alias = pieces[1].strip() if len(pieces) > 1 else ""
            result.append((name, alias))
        return result
    if names.startswith("* as "):
        return [("*", names.removeprefix("* as ").strip())]
    if "," in names:
        first, rest = names.split(",", 1)
        return [(first.strip(), "")] + _split_js_import_names(rest.strip())
    return [(names, "")]


def _js_signature(name: str, params: str, is_async: bool) -> str:
    prefix = "async " if is_async else ""
    cleaned = " ".join(str(params or "").replace("\n", " ").split())
    return f"{prefix}{name}({cleaned})"


def _js_call_names(stripped: str) -> list[str]:
    names: list[str] = []
    for match in _JS_CALL_RE.finditer(stripped):
        name = match.group("name")
        if name in _JS_CONTROL_WORDS:
            continue
        names.append(name)
    return _unique_preserve_case(names)


def _unique_preserve_case(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


class _AstCollector(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.symbols: list[SymbolRecord] = []
        self.imports: list[ImportRecord] = []
        self.calls: list[CallRecord] = []
        self._symbol_stack: list[str] = []
        self._class_stack: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        parent = self._symbol_stack[-1] if self._symbol_stack else ""
        qualified_name = _qualified_name(self._symbol_stack, node.name)
        symbol = SymbolRecord(
            name=node.name,
            qualified_name=qualified_name,
            kind=SymbolKind.CLASS,
            location=_location(self.path, node),
            parent=parent,
            docstring=ast.get_docstring(node) or "",
            decorators=[_unparse(item) for item in node.decorator_list],
            bases=[_unparse(item) for item in node.bases],
        )
        self.symbols.append(symbol)

        self._symbol_stack.append(qualified_name)
        self._class_stack.append(qualified_name)
        self.generic_visit(node)
        self._class_stack.pop()
        self._symbol_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self._visit_function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self._visit_function(node, is_async=True)

    def visit_Import(self, node: ast.Import) -> Any:
        for alias in node.names:
            self.imports.append(ImportRecord(
                path=self.path,
                line=getattr(node, "lineno", 0),
                module=alias.name,
                alias=alias.asname or "",
            ))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> Any:
        module = "." * int(node.level or 0) + (node.module or "")
        for alias in node.names:
            self.imports.append(ImportRecord(
                path=self.path,
                line=getattr(node, "lineno", 0),
                module=module,
                name=alias.name,
                alias=alias.asname or "",
            ))

    def visit_Call(self, node: ast.Call) -> Any:
        name = _call_name(node.func)
        if name:
            self.calls.append(CallRecord(
                path=self.path,
                line=getattr(node, "lineno", 0),
                name=name,
                enclosing_symbol=self._symbol_stack[-1] if self._symbol_stack else "",
            ))
        self.generic_visit(node)

    def _visit_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        *,
        is_async: bool,
    ) -> None:
        parent = self._symbol_stack[-1] if self._symbol_stack else ""
        qualified_name = _qualified_name(self._symbol_stack, node.name)
        kind = SymbolKind.METHOD if self._class_stack else SymbolKind.FUNCTION
        symbol = SymbolRecord(
            name=node.name,
            qualified_name=qualified_name,
            kind=kind,
            location=_location(self.path, node),
            signature=_signature(node, is_async=is_async),
            parent=parent,
            docstring=ast.get_docstring(node) or "",
            decorators=[_unparse(item) for item in node.decorator_list],
        )
        self.symbols.append(symbol)

        self._symbol_stack.append(qualified_name)
        self.generic_visit(node)
        self._symbol_stack.pop()


def _score_symbol(
    symbol: SymbolRecord,
    query: str,
    calls_by_symbol: dict[str, list[CallRecord]],
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    name = symbol.name.lower()
    qualified = symbol.qualified_name.lower()
    path = symbol.location.path.lower()
    docstring = symbol.docstring.lower()

    if query == name:
        score += 120
        reasons.append("exact name")
    elif query in name:
        score += 90
        reasons.append("name")

    if query == qualified:
        score += 120
        reasons.append("exact qualified name")
    elif query in qualified:
        score += 70
        reasons.append("qualified name")

    if query in path:
        score += 35
        reasons.append("path")

    if docstring and query in docstring:
        score += 25
        reasons.append("docstring")

    matching_calls = [
        call.name
        for call in calls_by_symbol.get(symbol.qualified_name, [])
        if query in call.name.lower()
    ]
    if matching_calls:
        score += 20
        reasons.append(f"calls {', '.join(sorted(set(matching_calls))[:3])}")

    return score, reasons


def _coerce_kind(kind: str | SymbolKind | None) -> SymbolKind | None:
    if kind is None or kind == "":
        return None
    if isinstance(kind, SymbolKind):
        return kind
    return SymbolKind(str(kind))


def _location(path: str, node: ast.AST) -> SourceLocation:
    line = int(getattr(node, "lineno", 0) or 0)
    end_line = int(getattr(node, "end_lineno", line) or line)
    column = int(getattr(node, "col_offset", 0) or 0)
    return SourceLocation(path=path, line=line, end_line=end_line, column=column)


def _qualified_name(stack: list[str], name: str) -> str:
    if not stack:
        return name
    return ".".join([stack[-1], name])


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef, *, is_async: bool) -> str:
    args = node.args
    parts: list[str] = []
    parts.extend(arg.arg for arg in args.posonlyargs)
    parts.extend(arg.arg for arg in args.args)
    if args.vararg:
        parts.append(f"*{args.vararg.arg}")
    elif args.kwonlyargs:
        parts.append("*")
    parts.extend(arg.arg for arg in args.kwonlyargs)
    if args.kwarg:
        parts.append(f"**{args.kwarg.arg}")
    prefix = "async " if is_async else ""
    return f"{prefix}{node.name}({', '.join(parts)})"


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        owner = _call_name(node.value)
        if owner:
            return f"{owner}.{node.attr}"
        return node.attr
    if isinstance(node, ast.Call):
        return _call_name(node.func)
    return ""


def _unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return node.__class__.__name__


def _symbol_label(symbol: SymbolRecord) -> str:
    if symbol.kind == SymbolKind.CLASS:
        return f"class {symbol.qualified_name}"
    if symbol.kind == SymbolKind.INTERFACE:
        return f"interface {symbol.qualified_name}"
    return f"{symbol.kind.value} {symbol.qualified_name}{_signature_suffix(symbol)}"


def _format_language_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "none"
    return ",".join(f"{language}:{count}" for language, count in sorted(counts.items()))


def _signature_suffix(symbol: SymbolRecord) -> str:
    if not symbol.signature:
        return ""
    prefix = "async " if symbol.signature.startswith("async ") else ""
    signature = symbol.signature[len(prefix):]
    open_paren = signature.find("(")
    if open_paren < 0:
        return ""
    return signature[open_paren:]


def _first_line(value: str) -> str:
    return value.strip().splitlines()[0][:180]


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _is_excluded(path: Path, root: Path, excluded_dirs: set[str]) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        parts = path.parts
    return any(part in excluded_dirs for part in parts)
