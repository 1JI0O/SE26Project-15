"""Compatibility facade for code analysis services.

New code should import focused modules from ``app.services.code_analysis``.
"""

from pathlib import Path
from typing import Any

from app.services.code_analysis.analyzer import analyze_code_archive, count_filtered_files
from app.services.code_analysis.editor import (
    FileAccessError,
    FileNotEditableError,
    FileTooLargeError,
    InvalidRepositoryPathError,
    RepositoryFileNotFoundError,
    is_editor_readable_file,
    read_repository_file,
    save_repository_file,
)
from app.services.code_analysis.python_ast import analyze_python
from app.services.code_analysis.tree import build_hierarchical_tree


def _analyze_python(path: str, source: str) -> dict[str, list[dict[str, Any]]]:
    analysis = analyze_python(path, source)
    return {
        "symbols": analysis.symbols,
        "imports": analysis.imports,
        "calls": analysis.calls,
        "pytorch_candidates": analysis.pytorch_candidates,
    }


def read_archive_file(
    archive_path: str | Path,
    file_path: str,
    *,
    edits_root: Path | None = None,
) -> str | None:
    try:
        return read_repository_file(archive_path, file_path, edits_root=edits_root)
    except RepositoryFileNotFoundError:
        return None


def save_archive_file_edit(
    edits_root: Path,
    file_path: str,
    content: str,
    *,
    archive_path: str | Path | None = None,
) -> Path:
    if archive_path is None:
        raise InvalidRepositoryPathError(
            "archive_path is required to validate repository membership"
        )
    return save_repository_file(archive_path, edits_root, file_path, content)


__all__ = [
    "FileAccessError",
    "FileNotEditableError",
    "FileTooLargeError",
    "InvalidRepositoryPathError",
    "RepositoryFileNotFoundError",
    "_analyze_python",
    "analyze_code_archive",
    "build_hierarchical_tree",
    "count_filtered_files",
    "is_editor_readable_file",
    "read_archive_file",
    "read_repository_file",
    "save_archive_file_edit",
    "save_repository_file",
]
