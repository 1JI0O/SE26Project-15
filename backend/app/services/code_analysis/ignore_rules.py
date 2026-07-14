from dataclasses import dataclass
from pathlib import PurePosixPath
from zipfile import ZipFile, ZipInfo

from pathspec import PathSpec

from app.services.code_analysis.constants import DEFAULT_IGNORE_PATTERNS, MAX_SOURCE_BYTES


@dataclass(frozen=True)
class IgnoreSpec:
    base_path: PurePosixPath
    spec: PathSpec


def _read_ignore_file(archive: ZipFile, member: ZipInfo) -> list[str]:
    with archive.open(member) as source:
        content = source.read(MAX_SOURCE_BYTES + 1)
    if len(content) > MAX_SOURCE_BYTES:
        return []
    return content.decode("utf-8", errors="replace").splitlines()


def build_ignore_specs(archive: ZipFile, members: list[ZipInfo]) -> list[IgnoreSpec]:
    specs = [
        IgnoreSpec(
            base_path=PurePosixPath("."),
            spec=PathSpec.from_lines("gitignore", DEFAULT_IGNORE_PATTERNS),
        )
    ]
    exclude_members: list[ZipInfo] = []
    gitignore_members: list[ZipInfo] = []
    for member in members:
        path = PurePosixPath(member.filename)
        if path.name == ".gitignore":
            gitignore_members.append(member)
        elif len(path.parts) >= 3 and path.parts[-3:] == (".git", "info", "exclude"):
            exclude_members.append(member)

    for member in sorted(exclude_members, key=lambda item: item.filename):
        path = PurePosixPath(member.filename)
        repository_root = PurePosixPath(*path.parts[:-3]) or PurePosixPath(".")
        specs.append(
            IgnoreSpec(
                base_path=repository_root,
                spec=PathSpec.from_lines("gitignore", _read_ignore_file(archive, member)),
            )
        )

    for member in sorted(
        gitignore_members,
        key=lambda item: (len(PurePosixPath(item.filename).parts), item.filename),
    ):
        path = PurePosixPath(member.filename)
        specs.append(
            IgnoreSpec(
                base_path=path.parent,
                spec=PathSpec.from_lines("gitignore", _read_ignore_file(archive, member)),
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


def is_ignored(path: PurePosixPath, specs: list[IgnoreSpec]) -> bool:
    ignored = False
    for ignore_spec in specs:
        relative_path = _relative_to_base(path, ignore_spec.base_path)
        if relative_path is None:
            continue
        match = ignore_spec.spec.check_file(relative_path)
        if match.include is not None:
            ignored = match.include
    return ignored
