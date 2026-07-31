"""Directory-based Python workspace analysis."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from pathspec import PathSpec

from tracelab_core.backend_path import ensure_backend_path


def _ignore_spec(workspace_root: Path) -> PathSpec:
    ensure_backend_path()
    from app.services.code_analysis.constants import DEFAULT_IGNORE_PATTERNS

    patterns = list(DEFAULT_IGNORE_PATTERNS)
    gitignore = workspace_root / ".gitignore"
    if gitignore.is_file():
        patterns.extend(gitignore.read_text(encoding="utf-8", errors="replace").splitlines())
    tracelab_ignore = workspace_root / ".tracelabignore"
    if tracelab_ignore.is_file():
        patterns.extend(tracelab_ignore.read_text(encoding="utf-8", errors="replace").splitlines())
    return PathSpec.from_lines("gitignore", patterns)


def _should_skip(spec: PathSpec, workspace_root: Path, path: Path) -> bool:
    rel = path.relative_to(workspace_root).as_posix()
    if rel.startswith(".tracelab/"):
        return True
    return spec.match_file(rel)


def _fingerprint(workspace_root: Path, py_files: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(py_files):
        rel = path.relative_to(workspace_root).as_posix()
        stat = path.stat()
        digest.update(rel.encode())
        digest.update(str(stat.st_mtime_ns).encode())
        digest.update(str(stat.st_size).encode())
    return digest.hexdigest()


def analyze_workspace(workspace_root: Path) -> dict[str, Any]:
    ensure_backend_path()
    from app.services.code_analysis.constants import MAX_SOURCE_BYTES
    from app.services.code_analysis.python_ast import analyze_python
    from app.services.tensor_flow.architecture import build_architecture_index
    from app.services.tensor_flow.semantic import build_tensor_graph

    workspace_root = workspace_root.resolve()
    spec = _ignore_spec(workspace_root)
    file_tree: list[dict[str, Any]] = []
    symbols: list[dict[str, Any]] = []
    imports: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    pytorch_candidates: list[dict[str, Any]] = []
    python_sources: list[tuple[str, str, Any]] = []
    py_files: list[Path] = []

    for dirpath, dirnames, filenames in os.walk(workspace_root):
        current = Path(dirpath)
        dirnames[:] = [
            name
            for name in dirnames
            if not _should_skip(spec, workspace_root, current / name)
        ]
        for filename in filenames:
            path = current / filename
            if _should_skip(spec, workspace_root, path):
                continue
            rel = path.relative_to(workspace_root).as_posix()
            size = path.stat().st_size
            language = "python" if rel.endswith(".py") else "other"
            file_tree.append(
                {
                    "path": rel,
                    "size": size,
                    "language": language,
                    "editable": language == "python" and size <= MAX_SOURCE_BYTES,
                }
            )
            if language != "python" or size > MAX_SOURCE_BYTES:
                continue
            source = path.read_text(encoding="utf-8", errors="replace")
            analysis = analyze_python(rel, source)
            symbols.extend(analysis.symbols)
            imports.extend(analysis.imports)
            calls.extend(analysis.calls)
            pytorch_candidates.extend(analysis.pytorch_candidates)
            if analysis.tree is not None:
                python_sources.append((rel, source, analysis.tree))
                py_files.append(path)

    tensor_graph = build_tensor_graph(python_sources, symbols)
    architecture_graph = build_architecture_index(python_sources, symbols)
    fingerprint = _fingerprint(workspace_root, py_files)

    return {
        "file_tree": file_tree,
        "symbols": symbols,
        "imports": imports,
        "calls": calls,
        "pytorch_candidates": pytorch_candidates,
        "tensor_graph": tensor_graph,
        "architecture_graph": architecture_graph,
        "revision": fingerprint,
        "summary": {
            "file_count": len(file_tree),
            "python_file_count": len(py_files),
            "symbol_count": len(symbols),
            "call_count": len(calls),
            "tensor_node_count": len(tensor_graph.get("nodes") or []),
            "architecture_roots": len((architecture_graph or {}).get("roots") or []),
        },
    }
