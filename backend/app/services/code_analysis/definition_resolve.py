"""Go-to-definition resolution using the static analysis index (non-LSP)."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.models.entities import CodeRepository
from app.services.code_analyzer import read_archive_file
from app.services.tensor_flow.architecture import _import_bindings, _module_name

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True)
class CallableSymbol:
    symbol_id: str
    path: str
    name: str
    line_start: int
    line_end: int
    owner_symbol_id: str | None = None


@dataclass
class DefinitionResolution:
    status: str
    symbol_id: str | None = None
    path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    reason: str | None = None
    candidates: list[dict[str, Any]] | None = None


class DefinitionIndex:
    """Lightweight symbol index mirroring ProjectCallableIndex heuristics."""

    def __init__(
        self,
        symbols: list[dict[str, Any]],
        imports_by_path: dict[str, dict[str, str]],
    ) -> None:
        self.imports_by_path = imports_by_path
        self.by_symbol_id = {str(item["id"]): item for item in symbols if item.get("id")}
        self.callables: dict[str, CallableSymbol] = {}
        self.methods: dict[tuple[str, str], CallableSymbol] = {}
        self.functions_by_name: dict[str, list[CallableSymbol]] = {}
        self.functions_by_canonical_name: dict[str, list[CallableSymbol]] = {}
        self.classes_by_name: dict[str, list[CallableSymbol]] = {}
        self.project_modules = {
            _module_name(str(item.get("path", "")))
            for item in symbols
            if item.get("path")
        }
        for item in symbols:
            callable_symbol = _callable_from_symbol(item)
            if callable_symbol is None:
                continue
            self.callables[callable_symbol.symbol_id] = callable_symbol
            if item.get("kind") == "class":
                self.classes_by_name.setdefault(callable_symbol.name, []).append(callable_symbol)
                continue
            if callable_symbol.owner_symbol_id:
                self.methods[(callable_symbol.owner_symbol_id, callable_symbol.name)] = (
                    callable_symbol
                )
                continue
            self.functions_by_name.setdefault(callable_symbol.name, []).append(callable_symbol)
            canonical = f"{_module_name(callable_symbol.path)}.{callable_symbol.name}"
            self.functions_by_canonical_name.setdefault(canonical, []).append(callable_symbol)

    def get(self, symbol_id: str) -> CallableSymbol | None:
        return self.callables.get(symbol_id)

    def canonical_callee(self, path: str, callee: str) -> str:
        root, separator, suffix = callee.partition(".")
        imported = self.imports_by_path.get(path, {}).get(root)
        if imported is None:
            return callee
        return f"{imported}.{suffix}" if separator else imported

    def resolve(self, caller: CallableSymbol, callee: str) -> DefinitionResolution:
        if callee == "dynamic_call":
            return DefinitionResolution(status="unresolved", reason="调用目标由运行时表达式决定")
        if callee.startswith("self."):
            method_name = callee.removeprefix("self.")
            if "." not in method_name and caller.owner_symbol_id:
                target = self.methods.get((caller.owner_symbol_id, method_name))
                if target is not None:
                    return _resolved(target)
                return DefinitionResolution(
                    status="unresolved",
                    reason=f"当前类中找不到唯一方法 {callee}",
                )
            return DefinitionResolution(status="unresolved", reason="无法解析 self 调用")

        short_name = callee.rsplit(".", 1)[-1]
        same_file = [
            candidate
            for candidate in self.functions_by_name.get(short_name, [])
            if candidate.path == caller.path
        ]
        if "." not in callee and len(same_file) == 1:
            return _resolved(same_file[0])
        if "." not in callee and len(same_file) > 1:
            return _ambiguous(same_file)

        canonical = self.canonical_callee(caller.path, callee)
        imported = self.functions_by_canonical_name.get(canonical, [])
        if len(imported) == 1:
            return _resolved(imported[0])
        if len(imported) > 1:
            return _ambiguous(imported, reason=f"项目中存在多个导入目标 {canonical}")

        global_matches = self.functions_by_name.get(short_name, [])
        if "." not in callee and len(global_matches) == 1:
            return _resolved(global_matches[0])
        if "." not in callee and len(global_matches) > 1:
            return _ambiguous(global_matches, reason=f"项目中存在多个名为 {short_name} 的函数")

        class_matches = self.classes_by_name.get(short_name, [])
        if "." not in callee and len(class_matches) == 1:
            return _resolved(class_matches[0])
        if "." not in callee and len(class_matches) > 1:
            return _ambiguous(class_matches, reason=f"项目中存在多个名为 {short_name} 的类")

        if canonical != callee and any(
            canonical == module or canonical.startswith(f"{module}.")
            for module in self.project_modules
        ):
            return DefinitionResolution(
                status="unresolved",
                reason=f"导入的项目调用 {callee} 无法定位到唯一函数",
            )
        return DefinitionResolution(status="unresolved", reason=f"无法解析 {callee}")

    def resolve_identifier(self, path: str, identifier: str) -> DefinitionResolution:
        name = identifier.strip()
        if not name:
            return DefinitionResolution(status="unresolved", reason="标识符为空")

        same_file = [
            item
            for item in self.callables.values()
            if item.path == path and item.name == name
        ]
        if len(same_file) == 1:
            return _resolved(same_file[0])
        if len(same_file) > 1:
            return _ambiguous(same_file)

        imported_root = name.split(".", 1)[0]
        binding = self.imports_by_path.get(path, {}).get(imported_root)
        if binding:
            canonical = self.canonical_callee(path, name)
            imported = self.functions_by_canonical_name.get(canonical, [])
            if len(imported) == 1:
                return _resolved(imported[0])
            if len(imported) > 1:
                return _ambiguous(imported)
            class_name = canonical.rsplit(".", 1)[-1]
            classes = self.classes_by_name.get(class_name, [])
            if len(classes) == 1:
                return _resolved(classes[0])
            if len(classes) > 1:
                return _ambiguous(classes)

        global_matches = self.functions_by_name.get(name, [])
        if len(global_matches) == 1:
            return _resolved(global_matches[0])
        if len(global_matches) > 1:
            return _ambiguous(global_matches, reason=f"项目中存在多个名为 {name} 的符号")

        classes = self.classes_by_name.get(name, [])
        if len(classes) == 1:
            return _resolved(classes[0])
        if len(classes) > 1:
            return _ambiguous(classes, reason=f"项目中存在多个名为 {name} 的类")

        return DefinitionResolution(status="unresolved", reason=f"找不到定义 {name}")


def _callable_from_symbol(item: dict[str, Any]) -> CallableSymbol | None:
    kind = str(item.get("kind", ""))
    if kind not in {"function", "method", "class"}:
        return None
    symbol_id = str(item.get("id", ""))
    path = str(item.get("path", ""))
    name = str(item.get("name", ""))
    if not symbol_id or not path or not name:
        return None
    line_start = int(item.get("line_start", item.get("line", 1)) or 1)
    line_end = int(item.get("line_end", line_start) or line_start)
    owner_symbol_id = None
    if kind == "method":
        qualified = str(item.get("qualified_name", ""))
        if "." in qualified:
            owner_name = qualified.rsplit(".", 1)[0]
            owner_symbol_id = f"{path}::{owner_name}"
    return CallableSymbol(
        symbol_id=symbol_id,
        path=path,
        name=name,
        line_start=line_start,
        line_end=line_end,
        owner_symbol_id=owner_symbol_id,
    )


def _resolved(target: CallableSymbol) -> DefinitionResolution:
    return DefinitionResolution(
        status="resolved",
        symbol_id=target.symbol_id,
        path=target.path,
        line_start=target.line_start,
        line_end=target.line_end,
    )


def _ambiguous(
    targets: list[CallableSymbol],
    *,
    reason: str | None = None,
) -> DefinitionResolution:
    return DefinitionResolution(
        status="ambiguous",
        reason=reason or "存在多个候选定义",
        candidates=[
            {
                "symbol_id": item.symbol_id,
                "path": item.path,
                "line_start": item.line_start,
                "line_end": item.line_end,
            }
            for item in targets
        ],
    )


def _analysis_payload(repository: CodeRepository) -> dict[str, Any]:
    if repository.analysis_json:
        return repository.analysis_json
    return {
        "symbols": repository.symbols_json or [],
        "imports": repository.imports_json or [],
        "calls": [],
    }


def _build_imports_by_path(
    repository: CodeRepository,
    *,
    edits_root: Path | None,
    paths: set[str] | None = None,
) -> dict[str, dict[str, str]]:
    imports_by_path: dict[str, dict[str, str]] = {}
    symbols = _analysis_payload(repository).get("symbols") or []
    candidate_paths = paths or {
        str(item.get("path", ""))
        for item in symbols
        if str(item.get("path", "")).endswith(".py")
    }
    for path in sorted(candidate_paths):
        if not path.endswith(".py"):
            continue
        source = read_archive_file(
            repository.storage_path,
            path,
            edits_root=edits_root,
        )
        if not source:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        imports_by_path[path] = _import_bindings(path, tree)
    return imports_by_path


def _find_call_at(
    calls: list[dict[str, Any]],
    *,
    path: str,
    line: int,
    column: int,
) -> dict[str, Any] | None:
    for call in calls:
        if call.get("path") != path:
            continue
        if int(call.get("line_start", -1)) != line:
            continue
        start = int(call.get("column_start", 0))
        end = int(call.get("column_end", start))
        if start <= column <= end:
            return call
    return None


def _extract_identifier(source: str, column: int) -> str | None:
    if not source:
        return None
    matches = list(_IDENTIFIER_RE.finditer(source))
    for match in matches:
        if match.start() <= column < match.end():
            text = match.group(0)
            # Expand left for dotted names like foo.bar
            expanded = text
            left = match.start()
            while left > 0 and source[left - 1] in {".", "_"}:
                prev = source[: left - 1]
                prior = list(_IDENTIFIER_RE.finditer(prev))
                if not prior:
                    break
                token = prior[-1]
                if token.end() != left - 1 or source[left - 1] != ".":
                    break
                expanded = f"{token.group(0)}.{expanded}" if source[left - 1] == "." else expanded
                left = token.start()
            right_end = match.end()
            while right_end < len(source) and source[right_end : right_end + 1] == ".":
                nxt = _IDENTIFIER_RE.match(source, right_end + 1)
                if not nxt:
                    break
                expanded = f"{expanded}.{nxt.group(0)}"
                right_end = nxt.end()
            return expanded
    return None


def resolve_definition(
    repository: CodeRepository,
    *,
    path: str,
    line: int,
    column: int,
    identifier: str | None,
    edits_root: Path | None,
) -> DefinitionResolution:
    if not path.endswith(".py"):
        return DefinitionResolution(status="unresolved", reason="仅支持 Python 文件")

    payload = _analysis_payload(repository)
    symbols = payload.get("symbols") or []
    calls = payload.get("calls") or []
    if not symbols:
        return DefinitionResolution(status="unresolved", reason="仓库尚未完成静态分析")

    imports_by_path = _build_imports_by_path(
        repository,
        edits_root=edits_root,
        paths={path},
    )
    # Include callee/import targets lazily when resolving cross-file calls.
    index = DefinitionIndex(symbols, imports_by_path)

    call = _find_call_at(calls, path=path, line=line, column=column)
    if call and call.get("caller_symbol_id") and call.get("callee"):
        caller = index.get(str(call["caller_symbol_id"]))
        callee = str(call["callee"])
        if caller:
            callee_path = caller.path
            needed_paths = {callee_path}
            if "." in callee:
                root = callee.split(".", 1)[0]
                binding = index.imports_by_path.get(callee_path, {}).get(root)
                if binding and "." in binding:
                    module_path = binding.replace(".", "/") + ".py"
                    needed_paths.add(module_path)
            extra_imports = _build_imports_by_path(
                repository,
                edits_root=edits_root,
                paths=needed_paths,
            )
            if extra_imports:
                index = DefinitionIndex(symbols, {**imports_by_path, **extra_imports})
                caller = index.get(str(call["caller_symbol_id"]))
            if caller:
                result = index.resolve(caller, callee)
                if result.status != "unresolved":
                    return result

    ident = (identifier or "").strip()
    if not ident:
        source = read_archive_file(repository.storage_path, path, edits_root=edits_root) or ""
        line_text = source.splitlines()[line - 1] if 1 <= line <= len(source.splitlines()) else ""
        ident = _extract_identifier(line_text, column) or ""

    if ident:
        return index.resolve_identifier(path, ident)

    return DefinitionResolution(status="unresolved", reason="无法解析光标处的符号")
