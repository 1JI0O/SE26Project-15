import ast
import zipfile
from pathlib import Path
from typing import Any

MAX_SOURCE_BYTES = 512_000


def _safe_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members: list[zipfile.ZipInfo] = []
    for member in archive.infolist():
        path = Path(member.filename)
        if member.is_dir() or path.is_absolute() or ".." in path.parts:
            continue
        members.append(member)
    return members


def _language_for(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix == ".py":
        return "python"
    if suffix in {".md", ".rst"}:
        return "docs"
    if suffix in {".yaml", ".yml", ".toml", ".json"}:
        return "config"
    return "other"


def _import_name(node: ast.AST) -> str:
    if isinstance(node, ast.Import):
        return ", ".join(alias.name for alias in node.names)
    if isinstance(node, ast.ImportFrom):
        module = node.module or ""
        names = ", ".join(alias.name for alias in node.names)
        return f"{module}:{names}" if module else names
    return ""


def _base_name(base: ast.expr) -> str:
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        parts = [base.attr]
        value = base.value
        while isinstance(value, ast.Attribute):
            parts.append(value.attr)
            value = value.value
        if isinstance(value, ast.Name):
            parts.append(value.id)
        return ".".join(reversed(parts))
    return ""


def _analyze_python(path: str, source: str) -> dict[str, list[dict[str, Any]]]:
    symbols: list[dict[str, Any]] = []
    imports: list[dict[str, Any]] = []
    pytorch_candidates: list[dict[str, Any]] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return {
            "symbols": [
                {
                    "path": path,
                    "type": "parse_error",
                    "name": exc.__class__.__name__,
                    "line": exc.lineno or 0,
                }
            ],
            "imports": imports,
            "pytorch_candidates": pytorch_candidates,
        }

    imports_torch = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            name = _import_name(node)
            imports_torch = imports_torch or "torch" in name or "torchvision" in name
            imports.append({"path": path, "name": name, "line": getattr(node, "lineno", 0)})
        elif isinstance(node, ast.ClassDef):
            bases = [_base_name(base) for base in node.bases]
            symbols.append(
                {
                    "path": path,
                    "type": "class",
                    "name": node.name,
                    "line": node.lineno,
                    "bases": bases,
                }
            )
            base_text = " ".join(bases)
            has_forward = any(
                isinstance(child, ast.FunctionDef) and child.name == "forward"
                for child in node.body
            )
            if "Module" in base_text or "nn.Module" in base_text or (imports_torch and has_forward):
                pytorch_candidates.append(
                    {
                        "path": path,
                        "name": node.name,
                        "line": node.lineno,
                        "reason": "Class looks like a torch.nn.Module implementation",
                    }
                )
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            symbols.append(
                {
                    "path": path,
                    "type": "function",
                    "name": node.name,
                    "line": node.lineno,
                    "args": [arg.arg for arg in node.args.args],
                }
            )

    return {"symbols": symbols, "imports": imports, "pytorch_candidates": pytorch_candidates}


def analyze_code_archive(path: str | Path) -> dict[str, list[dict[str, Any]]]:
    file_tree: list[dict[str, Any]] = []
    symbols: list[dict[str, Any]] = []
    imports: list[dict[str, Any]] = []
    pytorch_candidates: list[dict[str, Any]] = []

    with zipfile.ZipFile(path) as archive:
        for member in _safe_members(archive):
            file_tree.append(
                {
                    "path": member.filename,
                    "size": member.file_size,
                    "language": _language_for(member.filename),
                }
            )
            if not member.filename.endswith(".py") or member.file_size > MAX_SOURCE_BYTES:
                continue
            with archive.open(member) as source_file:
                source = source_file.read().decode("utf-8", errors="replace")
            analysis = _analyze_python(member.filename, source)
            symbols.extend(analysis["symbols"])
            imports.extend(analysis["imports"])
            pytorch_candidates.extend(analysis["pytorch_candidates"])

    return {
        "file_tree": file_tree,
        "symbols": symbols,
        "imports": imports,
        "pytorch_candidates": pytorch_candidates,
    }
