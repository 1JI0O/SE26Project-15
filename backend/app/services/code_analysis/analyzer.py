import zipfile
from pathlib import Path
from typing import Any

from app.services.code_analysis.archive import list_archive_entries, read_member_text
from app.services.code_analysis.constants import MAX_SOURCE_BYTES
from app.services.code_analysis.languages import is_editor_readable_file, language_for
from app.services.code_analysis.python_ast import analyze_python


def analyze_code_archive(
    path: str | Path,
    *,
    edits_root: Path | None = None,
) -> dict[str, Any]:
    file_tree: list[dict[str, Any]] = []
    symbols: list[dict[str, Any]] = []
    imports: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    pytorch_candidates: list[dict[str, Any]] = []
    python_sources: list[tuple[str, str, Any]] = []

    with zipfile.ZipFile(path) as archive:
        entries, archive_root, ignored_count = list_archive_entries(archive)
        for entry in entries:
            language = language_for(entry.display_path)
            file_tree.append(
                {
                    "path": entry.display_path,
                    "size": entry.size,
                    "language": language,
                    "editable": is_editor_readable_file(entry.display_path)
                    and entry.size <= MAX_SOURCE_BYTES,
                }
            )
            if language != "python" or entry.size > MAX_SOURCE_BYTES:
                continue
            source = read_member_text(archive, entry.member_name)
            if edits_root is not None:
                from app.services.code_analysis.editor import (
                    FileAccessError,
                    read_repository_file,
                )

                try:
                    source = read_repository_file(
                        path,
                        entry.display_path,
                        edits_root=edits_root,
                    )
                except FileAccessError:
                    pass
            analysis = analyze_python(entry.display_path, source)
            symbols.extend(analysis.symbols)
            imports.extend(analysis.imports)
            calls.extend(analysis.calls)
            pytorch_candidates.extend(analysis.pytorch_candidates)
            if analysis.tree is not None:
                python_sources.append((entry.display_path, source, analysis.tree))

    from app.services.tensor_flow.semantic import build_tensor_graph

    tensor_graph = build_tensor_graph(python_sources, symbols)
    return {
        "file_tree": file_tree,
        "symbols": symbols,
        "imports": imports,
        "calls": calls,
        "pytorch_candidates": pytorch_candidates,
        "tensor_graph": tensor_graph,
        "archive_root": archive_root,
        "summary": {
            "file_count": len(file_tree),
            "python_file_count": sum(item["language"] == "python" for item in file_tree),
            "symbol_count": len(symbols),
            "call_count": len(calls),
            "ignored_count": ignored_count,
            "total_bytes": sum(int(item["size"]) for item in file_tree),
        },
    }


def count_filtered_files(path: str | Path) -> int:
    with zipfile.ZipFile(path) as archive:
        _entries, _root, ignored_count = list_archive_entries(archive)
    return ignored_count
