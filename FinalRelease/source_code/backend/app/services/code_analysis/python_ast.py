import ast
from dataclasses import dataclass, field
from typing import Any


def expression_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        owner = expression_name(node.value)
        return f"{owner}.{node.attr}" if owner else node.attr
    if isinstance(node, ast.Call):
        return expression_name(node.func)
    return ""


def _import_name(node: ast.Import | ast.ImportFrom) -> str:
    if isinstance(node, ast.Import):
        return ", ".join(alias.name for alias in node.names)
    module = node.module or ""
    names = ", ".join(alias.name for alias in node.names)
    return f"{module}:{names}" if module else names


@dataclass
class PythonAnalysis:
    tree: ast.Module | None = None
    symbols: list[dict[str, Any]] = field(default_factory=list)
    imports: list[dict[str, Any]] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)
    pytorch_candidates: list[dict[str, Any]] = field(default_factory=list)


class PythonAnalyzer(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.analysis = PythonAnalysis()
        self.scope: list[tuple[str, str]] = []
        self.current_callable: list[str] = []
        self.imports_torch = False

    @property
    def qualified_scope(self) -> str:
        return ".".join(name for name, _kind in self.scope)

    def _symbol(self, node: ast.AST, name: str, kind: str, **extra: Any) -> dict[str, Any]:
        qualified_name = f"{self.qualified_scope}.{name}" if self.scope else name
        line_start = getattr(node, "lineno", 1)
        line_end = getattr(node, "end_lineno", line_start)
        return {
            "id": f"{self.path}::{qualified_name}",
            "kind": kind,
            "type": kind,
            "name": name,
            "path": self.path,
            "line": line_start,
            "line_start": line_start,
            "line_end": line_end,
            "qualified_name": qualified_name,
            **extra,
        }

    def visit_Import(self, node: ast.Import) -> None:
        self._add_import(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self._add_import(node)

    def _add_import(self, node: ast.Import | ast.ImportFrom) -> None:
        name = _import_name(node)
        self.imports_torch = self.imports_torch or "torch" in name or "torchvision" in name
        self.analysis.imports.append(
            {
                "path": self.path,
                "name": name,
                "line": node.lineno,
                "line_start": node.lineno,
                "line_end": node.end_lineno or node.lineno,
            }
        )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        bases = [expression_name(base) for base in node.bases]
        symbol = self._symbol(node, node.name, "class", bases=bases)
        self.analysis.symbols.append(symbol)
        has_forward = any(
            isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) and child.name == "forward"
            for child in node.body
        )
        if any(base.endswith("Module") for base in bases) or (self.imports_torch and has_forward):
            self.analysis.pytorch_candidates.append(
                {
                    "id": symbol["id"],
                    "path": self.path,
                    "name": node.name,
                    "line": node.lineno,
                    "line_start": node.lineno,
                    "line_end": node.end_lineno or node.lineno,
                    "reason": "Class looks like a torch.nn.Module implementation",
                }
            )
        self.scope.append((node.name, "class"))
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        parent_kind = self.scope[-1][1] if self.scope else None
        kind = "method" if parent_kind == "class" else "function"
        symbol = self._symbol(
            node,
            node.name,
            kind,
            args=[arg.arg for arg in node.args.args],
            is_async=isinstance(node, ast.AsyncFunctionDef),
        )
        self.analysis.symbols.append(symbol)
        self.scope.append((node.name, kind))
        self.current_callable.append(symbol["id"])
        self.generic_visit(node)
        self.current_callable.pop()
        self.scope.pop()

    def visit_Call(self, node: ast.Call) -> None:
        callee = expression_name(node.func) or "<dynamic>"
        line_end = node.end_lineno or node.lineno
        self.analysis.calls.append(
            {
                "id": f"{self.path}:{node.lineno}:{node.col_offset}:{callee}",
                "caller_symbol_id": self.current_callable[-1] if self.current_callable else None,
                "callee": callee,
                "path": self.path,
                "line_start": node.lineno,
                "line_end": line_end,
                "column_start": node.col_offset,
                "column_end": node.end_col_offset or node.col_offset,
            }
        )
        self.generic_visit(node)


def analyze_python(path: str, source: str) -> PythonAnalysis:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        line = exc.lineno or 1
        return PythonAnalysis(
            symbols=[
                {
                    "id": f"{path}::<parse-error>",
                    "kind": "parse_error",
                    "type": "parse_error",
                    "name": exc.__class__.__name__,
                    "path": path,
                    "line": line,
                    "line_start": line,
                    "line_end": line,
                    "qualified_name": "<parse-error>",
                }
            ]
        )
    analyzer = PythonAnalyzer(path)
    analyzer.analysis.tree = tree
    analyzer.visit(tree)
    return analyzer.analysis
