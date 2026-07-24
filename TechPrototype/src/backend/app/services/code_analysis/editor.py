import zipfile
from pathlib import Path

from app.services.code_analysis.archive import (
    list_archive_entries,
    normalize_relative_path,
    read_member_bytes,
)
from app.services.code_analysis.constants import MAX_EDIT_BYTES, MAX_SOURCE_BYTES
from app.services.code_analysis.languages import is_editor_readable_file


class FileAccessError(ValueError):
    pass


class InvalidRepositoryPathError(FileAccessError):
    pass


class RepositoryFileNotFoundError(FileAccessError):
    pass


class FileNotEditableError(FileAccessError):
    pass


class FileTooLargeError(FileAccessError):
    pass


def _normalized_path(file_path: str) -> str:
    try:
        return normalize_relative_path(file_path)
    except ValueError as exc:
        raise InvalidRepositoryPathError(str(exc)) from exc


def _entry_for_path(archive: zipfile.ZipFile, file_path: str):
    entries, _root, _ignored = list_archive_entries(archive)
    matches = [entry for entry in entries if entry.display_path == file_path]
    if len(matches) != 1:
        raise RepositoryFileNotFoundError(f"Code file not found: {file_path}")
    return matches[0]


def _safe_edit_target(edits_root: Path, normalized_path: str) -> Path:
    root = edits_root.resolve()
    target = (root / normalized_path).resolve()
    if target == root or root not in target.parents:
        raise InvalidRepositoryPathError("Edit path escapes the repository edit directory")
    return target


def _decode_text(data: bytes, file_path: str) -> str:
    if b"\x00" in data:
        raise FileNotEditableError(f"Binary file cannot be opened in the editor: {file_path}")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FileNotEditableError(
            f"File is not valid UTF-8 text and cannot be edited: {file_path}"
        ) from exc


def read_repository_file(
    archive_path: str | Path,
    file_path: str,
    *,
    edits_root: Path | None = None,
) -> str:
    normalized_path = _normalized_path(file_path)
    if not is_editor_readable_file(normalized_path):
        raise FileNotEditableError(f"File type is not editable: {normalized_path}")
    with zipfile.ZipFile(archive_path) as archive:
        entry = _entry_for_path(archive, normalized_path)
        if entry.size > MAX_SOURCE_BYTES:
            raise FileTooLargeError(
                f"File exceeds the {MAX_SOURCE_BYTES}-byte editor limit: {normalized_path}"
            )
        if edits_root is not None:
            edited_file = _safe_edit_target(edits_root, normalized_path)
            if edited_file.is_symlink():
                raise InvalidRepositoryPathError("Symbolic links are not allowed in edit storage")
            if edited_file.is_file():
                if edited_file.stat().st_size > MAX_SOURCE_BYTES:
                    raise FileTooLargeError(
                        f"Edited file exceeds the {MAX_SOURCE_BYTES}-byte editor limit"
                    )
                return _decode_text(edited_file.read_bytes(), normalized_path)
        return _decode_text(read_member_bytes(archive, entry.member_name), normalized_path)


def save_repository_file(
    archive_path: str | Path,
    edits_root: Path,
    file_path: str,
    content: str,
) -> Path:
    normalized_path = _normalized_path(file_path)
    if not is_editor_readable_file(normalized_path):
        raise FileNotEditableError(f"File type is not editable: {normalized_path}")
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_EDIT_BYTES:
        raise FileTooLargeError(f"Edited content exceeds the {MAX_EDIT_BYTES}-byte limit")
    with zipfile.ZipFile(archive_path) as archive:
        _entry_for_path(archive, normalized_path)
    target = _safe_edit_target(edits_root, normalized_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    has_symlink_parent = any(
        parent.is_symlink() for parent in target.parents if parent != edits_root
    )
    if target.is_symlink() or has_symlink_parent:
        raise InvalidRepositoryPathError("Symbolic links are not allowed in edit storage")
    target.write_bytes(encoded)
    return target


__all__ = [
    "FileAccessError",
    "FileNotEditableError",
    "FileTooLargeError",
    "InvalidRepositoryPathError",
    "RepositoryFileNotFoundError",
    "is_editor_readable_file",
    "read_repository_file",
    "save_repository_file",
]
