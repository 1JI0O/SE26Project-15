import ast
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from pathspec import PathSpec

MAX_SOURCE_BYTES = 512_000

# Default ignore patterns for filtering files
DEFAULT_IGNORE_PATTERNS = [
    ".DS_Store",
    "._*",
    ".AppleDouble/",
    ".LSOverride",
    "__MACOSX/",
    "MACOSX/",
    "MACOS_*/",
    ".Spotlight-V100/",
    ".TemporaryItems/",
    ".Trashes/",
    ".fseventsd/",
]


@dataclass(frozen=True)
class IgnoreSpec:
    base_path: PurePosixPath
    spec: PathSpec


def _zip_path(filename: str) -> PurePosixPath:
    return PurePosixPath(filename)


def _safe_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members: list[zipfile.ZipInfo] = []
    for member in archive.infolist():
        path = _zip_path(member.filename)
        if member.is_dir() or path.is_absolute() or ".." in path.parts:
            continue
        members.append(member)
    return members


def _read_member_text(archive: zipfile.ZipFile, member: zipfile.ZipInfo) -> str:
    with archive.open(member) as source_file:
        return source_file.read().decode("utf-8", errors="replace")


def _build_ignore_specs(
    archive: zipfile.ZipFile,
    members: list[zipfile.ZipInfo],
) -> list[IgnoreSpec]:
    specs = [
        IgnoreSpec(
            base_path=PurePosixPath("."),
            spec=PathSpec.from_lines("gitignore", DEFAULT_IGNORE_PATTERNS),
        )
    ]

    for member in members:
        path = _zip_path(member.filename)
        if path.name != ".gitignore":
            continue
        lines = _read_member_text(archive, member).splitlines()
        specs.append(
            IgnoreSpec(
                base_path=path.parent,
                spec=PathSpec.from_lines("gitignore", lines),
            )
        )
    return specs


def _relative_to_base(path: PurePosixPath, base_path: PurePosixPath) -> str | None:
    if str(base_path) == ".":
        return path.as_posix()
    try:
        return path.relative_to(base_path).as_posix()
    except ValueError:
        return None


def _is_macos_artifact(path: PurePosixPath) -> bool:
    return any(
        part == ".DS_Store"
        or part == "__MACOSX"
        or part == "MACOSX"
        or part.startswith("MACOS_")
        or part.startswith("._")
        for part in path.parts
    )


def _is_ignored(path: PurePosixPath, specs: list[IgnoreSpec]) -> bool:
    if _is_macos_artifact(path):
        return True

    for ignore_spec in specs:
        relative_path = _relative_to_base(path, ignore_spec.base_path)
        if relative_path and ignore_spec.spec.match_file(relative_path):
            return True
    return False


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
        safe_members = _safe_members(archive)
        ignore_specs = _build_ignore_specs(archive, safe_members)
        for member in safe_members:
            member_path = _zip_path(member.filename)
            if _is_ignored(member_path, ignore_specs):
                continue
            file_tree.append(
                {
                    "path": member.filename,
                    "size": member.file_size,
                    "language": _language_for(member.filename),
                }
            )
            if not member.filename.endswith(".py") or member.file_size > MAX_SOURCE_BYTES:
                continue
            source = _read_member_text(archive, member)
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
