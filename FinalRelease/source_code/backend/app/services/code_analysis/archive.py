import stat
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath

from app.services.code_analysis.constants import (
    MAX_ARCHIVE_FILES,
    MAX_ARCHIVE_UNCOMPRESSED_BYTES,
)
from app.services.code_analysis.ignore_rules import build_ignore_specs, is_ignored


class InvalidCodeArchiveError(ValueError):
    pass


@dataclass(frozen=True)
class ArchiveEntry:
    member_name: str
    display_path: str
    size: int


def normalize_relative_path(path: str) -> str:
    candidate = path.replace("\\", "/")
    pure_path = PurePosixPath(candidate)
    if (
        not candidate
        or candidate.startswith("/")
        or pure_path.is_absolute()
        or any(part in {"", ".", ".."} for part in pure_path.parts)
        or (pure_path.parts and ":" in pure_path.parts[0])
    ):
        raise ValueError("Path must be a normalized repository-relative path")
    return pure_path.as_posix()


def _is_zip_symlink(member: zipfile.ZipInfo) -> bool:
    unix_mode = member.external_attr >> 16
    return stat.S_ISLNK(unix_mode)


def safe_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    if len(archive.infolist()) > MAX_ARCHIVE_FILES:
        raise InvalidCodeArchiveError(f"Archive contains more than {MAX_ARCHIVE_FILES} entries")
    members: list[zipfile.ZipInfo] = []
    total_size = 0
    for member in archive.infolist():
        if member.is_dir() or _is_zip_symlink(member) or "\\" in member.filename:
            continue
        try:
            normalize_relative_path(member.filename)
        except ValueError:
            continue
        members.append(member)
        total_size += member.file_size
        if len(members) > MAX_ARCHIVE_FILES:
            raise InvalidCodeArchiveError(f"Archive contains more than {MAX_ARCHIVE_FILES} files")
        if total_size > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
            raise InvalidCodeArchiveError("Archive uncompressed size exceeds the safety limit")
    return members


def common_top_folder(paths: list[str]) -> str:
    if not paths:
        return ""
    first_parts = [path.split("/", 1)[0] for path in paths]
    candidate = first_parts[0]
    if all(path.startswith(f"{candidate}/") for path in paths):
        return candidate
    return ""


def list_archive_entries(archive: zipfile.ZipFile) -> tuple[list[ArchiveEntry], str, int]:
    members = safe_members(archive)
    specs = build_ignore_specs(archive, members)
    included = [
        member for member in members if not is_ignored(PurePosixPath(member.filename), specs)
    ]
    root = common_top_folder([member.filename for member in included])
    prefix = f"{root}/" if root else ""
    entries: list[ArchiveEntry] = []
    display_paths: set[str] = set()
    for member in included:
        display_path = member.filename[len(prefix) :] if prefix else member.filename
        if not display_path:
            continue
        if display_path in display_paths:
            raise InvalidCodeArchiveError(f"Archive contains a duplicate path: {display_path}")
        display_paths.add(display_path)
        entries.append(
            ArchiveEntry(
                member_name=member.filename,
                display_path=display_path,
                size=member.file_size,
            )
        )
    return entries, root, len(members) - len(included)


def read_member_bytes(archive: zipfile.ZipFile, member_name: str) -> bytes:
    with archive.open(member_name) as source:
        return source.read()


def read_member_text(archive: zipfile.ZipFile, member_name: str) -> str:
    return read_member_bytes(archive, member_name).decode("utf-8", errors="replace")
