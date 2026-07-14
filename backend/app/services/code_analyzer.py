import ast
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from pathspec import PathSpec

# Maximum number of bytes to read from a source file.
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
    if not is_editor_readable_file(path):
        return "binary"
    return "other"


EDITOR_READABLE_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".java",
    ".kt",
    ".go",
    ".rs",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".swift",
    ".rb",
    ".php",
    ".lua",
    ".sh",
    ".bash",
    ".zsh",
    ".ps1",
    ".bat",
    ".cmd",
    ".md",
    ".rst",
    ".txt",
    ".text",
    ".log",
    ".yaml",
    ".yml",
    ".toml",
    ".json",
    ".jsonl",
    ".xml",
    ".html",
    ".htm",
    ".css",
    ".scss",
    ".less",
    ".vue",
    ".svelte",
    ".ini",
    ".cfg",
    ".conf",
    ".env",
    ".properties",
    ".sql",
    ".csv",
    ".tsv",
    ".gitignore",
    ".dockerignore",
    ".editorconfig",
}

EDITOR_READABLE_BASENAMES = {
    "makefile",
    "dockerfile",
    "license",
    "readme",
    "cmakelists.txt",
}

BLOCKED_BINARY_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".bmp",
    ".ico",
    ".tif",
    ".tiff",
    ".pt",
    ".pth",
    ".ckpt",
    ".safetensors",
    ".bin",
    ".onnx",
    ".h5",
    ".hdf5",
    ".pb",
    ".tflite",
    ".npy",
    ".npz",
    ".pkl",
    ".pickle",
    ".parquet",
    ".feather",
    ".arrow",
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".7z",
    ".rar",
    ".mp4",
    ".mp3",
    ".wav",
    ".avi",
    ".mov",
    ".ttf",
    ".otf",
    ".woff",
    ".woff2",
    ".pdf",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".o",
    ".a",
    ".class",
    ".jar",
    ".wasm",
    ".db",
    ".sqlite",
}


def is_editor_readable_file(path: str) -> bool:
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix in BLOCKED_BINARY_EXTENSIONS:
        return False
    if suffix in EDITOR_READABLE_EXTENSIONS:
        return True
    return file_path.name.lower() in EDITOR_READABLE_BASENAMES


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
        raw_paths: list[str] = []
        for member in safe_members:
            member_path = _zip_path(member.filename)
            if _is_ignored(member_path, ignore_specs):
                continue
            raw_paths.append(member.filename)

        common_root = _common_top_folder(raw_paths)
        root_prefix = f"{common_root}/" if common_root else ""

        for member in safe_members:
            member_path = _zip_path(member.filename)
            if _is_ignored(member_path, ignore_specs):
                continue
            normalized_path = member.filename
            if root_prefix and normalized_path.startswith(root_prefix):
                normalized_path = normalized_path[len(root_prefix) :]
            elif common_root and normalized_path == common_root:
                continue

            file_tree.append(
                {
                    "path": normalized_path,
                    "size": member.file_size,
                    "language": _language_for(normalized_path),
                }
            )
            if not normalized_path.endswith(".py") or member.file_size > MAX_SOURCE_BYTES:
                continue
            source = _read_member_text(archive, member)
            analysis = _analyze_python(normalized_path, source)
            symbols.extend(analysis["symbols"])
            imports.extend(analysis["imports"])
            pytorch_candidates.extend(analysis["pytorch_candidates"])

    return {
        "file_tree": file_tree,
        "symbols": symbols,
        "imports": imports,
        "pytorch_candidates": pytorch_candidates,
        "archive_root": common_root,
    }


def _meta_for_language(language: str) -> str:
    mapping = {
        "python": "python",
        "docs": "doc",
        "config": "config",
    }
    return mapping.get(language, "file")


def build_hierarchical_tree(
    file_tree: list[dict[str, Any]],
    *,
    root_name: str = "repository",
) -> list[dict[str, Any]]:
    if not file_tree:
        return []

    entries = sorted(file_tree, key=lambda item: item["path"])
    tree: dict[str, Any] = {"children": {}}

    for item in entries:
        relative_path = str(item["path"])
        parts = [part for part in relative_path.split("/") if part]
        if not parts:
            continue
        node = tree
        for index, part in enumerate(parts):
            children = node.setdefault("children", {})
            is_file = index == len(parts) - 1
            full_path = "/".join(parts[: index + 1])
            if part not in children:
                children[part] = {
                    "name": part,
                    "path": full_path,
                    "kind": "file" if is_file else "folder",
                    "meta": (
                        _meta_for_language(str(item.get("language", "file"))) if is_file else ""
                    ),
                    "children": {},
                }
            node = children[part]
            if is_file:
                node["meta"] = _meta_for_language(str(item.get("language", "file")))

    def serialize(node_map: dict[str, Any]) -> list[dict[str, Any]]:
        serialized: list[dict[str, Any]] = []
        for name in sorted(
            node_map.keys(), key=lambda key: (node_map[key]["kind"] != "folder", key)
        ):
            current = node_map[name]
            child_map = current.get("children", {})
            children = serialize(child_map) if child_map else []
            if current["kind"] == "folder":
                file_count = sum(1 for child in children if child["kind"] == "file")
                folder_count = sum(1 for child in children if child["kind"] == "folder")
                current["meta"] = (
                    "root"
                    if not current["path"]
                    else f"{folder_count} folders, {file_count} files"
                    if folder_count
                    else f"{file_count} files"
                )
            serialized.append(
                {
                    "name": current["name"],
                    "path": current["path"],
                    "kind": current["kind"],
                    "meta": current["meta"],
                    "children": children,
                }
            )
        return serialized

    return [
        {
            "name": root_name,
            "path": "",
            "kind": "folder",
            "meta": "root",
            "children": serialize(tree["children"]),
        }
    ]


def _common_top_folder(paths: list[str]) -> str:
    if not paths:
        return ""
    first_parts = [path.split("/")[0] for path in paths if "/" in path]
    if not first_parts:
        return ""
    candidate = first_parts[0]
    if all(path.startswith(f"{candidate}/") or path == candidate for path in paths):
        return candidate
    return ""


def _allowed_paths(archive_path: str | Path) -> set[str]:
    with zipfile.ZipFile(archive_path) as archive:
        safe_members = _safe_members(archive)
        ignore_specs = _build_ignore_specs(archive, safe_members)
        allowed: set[str] = set()
        for member in safe_members:
            member_path = _zip_path(member.filename)
            if _is_ignored(member_path, ignore_specs):
                continue
            allowed.add(member.filename)
        return allowed


def _resolve_archive_member_path(archive_path: str | Path, file_path: str) -> str | None:
    normalized_path = file_path.lstrip("/")
    allowed = _allowed_paths(archive_path)
    if normalized_path in allowed:
        return normalized_path

    candidates = [
        path
        for path in allowed
        if path.endswith(f"/{normalized_path}") or path == normalized_path
    ]
    if len(candidates) == 1:
        return candidates[0]
    return None


def read_archive_file(
    archive_path: str | Path,
    file_path: str,
    *,
    edits_root: Path | None = None,
) -> str | None:
    normalized_path = file_path.lstrip("/")
    if edits_root is not None:
        edited_file = edits_root / normalized_path
        if edited_file.is_file():
            return edited_file.read_text(encoding="utf-8", errors="replace")

    member_path = _resolve_archive_member_path(archive_path, normalized_path)
    if member_path is None:
        return None

    with zipfile.ZipFile(archive_path) as archive:
        member = archive.getinfo(member_path)
        if member.file_size > MAX_SOURCE_BYTES:
            return _read_member_text(archive, member)[:MAX_SOURCE_BYTES]
        return _read_member_text(archive, member)


def save_archive_file_edit(edits_root: Path, file_path: str, content: str) -> Path:
    normalized_path = file_path.lstrip("/")
    target = edits_root / normalized_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def count_filtered_files(archive_path: str | Path) -> int:
    with zipfile.ZipFile(archive_path) as archive:
        safe_members = _safe_members(archive)
        ignore_specs = _build_ignore_specs(archive, safe_members)
        ignored = 0
        for member in safe_members:
            member_path = _zip_path(member.filename)
            if _is_ignored(member_path, ignore_specs):
                ignored += 1
        return ignored
