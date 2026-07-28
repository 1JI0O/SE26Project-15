import stat
import zipfile
from pathlib import Path, PurePosixPath

import pytest

from app.services.code_analysis import archive as archive_module
from app.services.code_analysis import editor as editor_module
from app.services.code_analysis.analyzer import analyze_code_archive, count_filtered_files
from app.services.code_analysis.archive import (
    InvalidCodeArchiveError,
    common_top_folder,
    list_archive_entries,
    safe_members,
)
from app.services.code_analysis.constants import MAX_SOURCE_BYTES
from app.services.code_analysis.editor import (
    FileNotEditableError,
    FileTooLargeError,
    InvalidRepositoryPathError,
    read_repository_file,
    save_repository_file,
)
from app.services.code_analysis.ignore_rules import build_ignore_specs, is_ignored
from app.services.code_analysis.languages import language_for
from app.services.code_analysis.python_ast import analyze_python
from app.services.code_analysis.tree import build_hierarchical_tree


def _write_zip(path: Path, entries: dict[str, str | bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for filename, content in entries.items():
            archive.writestr(filename, content)


def test_analysis_falls_back_to_archived_source_when_edit_is_invalid(tmp_path: Path) -> None:
    archive_path = tmp_path / "repository.zip"
    edits_root = tmp_path / "edits"
    _write_zip(archive_path, {"repo/model.py": "def archived():\n    return 1\n"})
    edited_file = edits_root / "model.py"
    edited_file.parent.mkdir(parents=True)
    edited_file.write_bytes(b"def edited():\x00\n")

    analysis = analyze_code_archive(archive_path, edits_root=edits_root)

    assert {symbol["name"] for symbol in analysis["symbols"]} == {"archived"}


def test_count_filtered_files_reports_default_ignores(tmp_path: Path) -> None:
    archive_path = tmp_path / "repository.zip"
    _write_zip(
        archive_path,
        {
            "repo/model.py": "VALUE = 1\n",
            "repo/__pycache__/model.pyc": b"compiled",
        },
    )

    assert count_filtered_files(archive_path) == 1


def test_safe_members_skips_directories_links_and_unsafe_paths(tmp_path: Path) -> None:
    archive_path = tmp_path / "unsafe.zip"
    symlink = zipfile.ZipInfo("link.py")
    symlink.create_system = 3
    symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("folder/", b"")
        archive.writestr(symlink, b"target.py")
        archive.writestr("/absolute.py", b"VALUE = 2\n")
        archive.writestr("../escape.py", b"VALUE = 3\n")
        archive.writestr("safe.py", b"VALUE = 4\n")

    with zipfile.ZipFile(archive_path) as archive:
        assert [member.filename for member in safe_members(archive)] == ["safe.py"]


def test_safe_members_rejects_excessive_entry_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(archive_module, "MAX_ARCHIVE_FILES", 1)

    class Archive:
        @staticmethod
        def infolist() -> list[zipfile.ZipInfo]:
            return [zipfile.ZipInfo("one.py"), zipfile.ZipInfo("two.py")]

    with pytest.raises(InvalidCodeArchiveError, match="more than 1 entries"):
        safe_members(Archive())  # type: ignore[arg-type]


def test_safe_members_defends_against_growing_member_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(archive_module, "MAX_ARCHIVE_FILES", 1)

    class MisreportedMembers(list[zipfile.ZipInfo]):
        def __len__(self) -> int:
            return 1

    members = MisreportedMembers([zipfile.ZipInfo("one.py"), zipfile.ZipInfo("two.py")])

    class Archive:
        @staticmethod
        def infolist() -> MisreportedMembers:
            return members

    with pytest.raises(InvalidCodeArchiveError, match="more than 1 files"):
        safe_members(Archive())  # type: ignore[arg-type]


def test_safe_members_rejects_excessive_uncompressed_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(archive_module, "MAX_ARCHIVE_UNCOMPRESSED_BYTES", 0)
    member = zipfile.ZipInfo("model.py")
    member.file_size = 1

    class Archive:
        @staticmethod
        def infolist() -> list[zipfile.ZipInfo]:
            return [member]

    with pytest.raises(InvalidCodeArchiveError, match="uncompressed size"):
        safe_members(Archive())  # type: ignore[arg-type]


def test_empty_archive_has_no_common_top_folder() -> None:
    assert common_top_folder([]) == ""
    assert common_top_folder(["model.py", "src/model.py"]) == ""


def test_archive_listing_discards_an_empty_display_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    member = zipfile.ZipInfo("root/")
    monkeypatch.setattr(archive_module, "safe_members", lambda _archive: [member])

    entries, root, ignored_count = list_archive_entries(object())  # type: ignore[arg-type]

    assert entries == []
    assert root == "root"
    assert ignored_count == 0


def test_oversized_ignore_file_is_not_applied(tmp_path: Path) -> None:
    archive_path = tmp_path / "repository.zip"
    _write_zip(
        archive_path,
        {
            "repo/.gitignore": b"x" * (MAX_SOURCE_BYTES + 1),
            "repo/model.py": "VALUE = 1\n",
        },
    )

    with zipfile.ZipFile(archive_path) as archive:
        members = safe_members(archive)
        specs = build_ignore_specs(archive, members)

    assert not is_ignored(PurePosixPath("repo/model.py"), specs)


def test_read_rejects_invalid_utf8_and_oversized_archive_files(tmp_path: Path) -> None:
    invalid_archive = tmp_path / "invalid.zip"
    large_archive = tmp_path / "large.zip"
    _write_zip(invalid_archive, {"repo/model.py": b"\xff"})
    _write_zip(large_archive, {"repo/model.py": b"x" * (MAX_SOURCE_BYTES + 1)})

    with pytest.raises(FileNotEditableError, match="valid UTF-8"):
        read_repository_file(invalid_archive, "model.py")
    with pytest.raises(FileTooLargeError, match="editor limit"):
        read_repository_file(large_archive, "model.py")


def test_read_and_save_reject_binary_file_types(tmp_path: Path) -> None:
    archive_path = tmp_path / "repository.zip"
    _write_zip(archive_path, {"repo/logo.png": b"not-an-image"})

    with pytest.raises(FileNotEditableError, match="not editable"):
        read_repository_file(archive_path, "logo.png")
    with pytest.raises(FileNotEditableError, match="not editable"):
        save_repository_file(archive_path, tmp_path / "edits", "logo.png", "content")


def test_edit_target_cannot_equal_the_edit_root(tmp_path: Path) -> None:
    with pytest.raises(InvalidRepositoryPathError, match="escapes"):
        editor_module._safe_edit_target(tmp_path, ".")


def test_read_rejects_symlink_and_oversized_edit_overlays(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_path = tmp_path / "repository.zip"
    edits_root = tmp_path / "edits"
    _write_zip(archive_path, {"repo/model.py": "VALUE = 1\n"})
    edited_file = edits_root / "model.py"
    edited_file.parent.mkdir(parents=True)
    edited_file.write_text("VALUE = 2\n", encoding="utf-8")

    monkeypatch.setattr(Path, "is_symlink", lambda self: self == edited_file)
    with pytest.raises(InvalidRepositoryPathError, match="Symbolic links"):
        read_repository_file(archive_path, "model.py", edits_root=edits_root)

    monkeypatch.undo()
    edited_file.write_bytes(b"x" * (MAX_SOURCE_BYTES + 1))
    with pytest.raises(FileTooLargeError, match="Edited file exceeds"):
        read_repository_file(archive_path, "model.py", edits_root=edits_root)


def test_save_rejects_symlinked_parent_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_path = tmp_path / "repository.zip"
    edits_root = tmp_path / "edits"
    _write_zip(archive_path, {"repo/nested/model.py": "VALUE = 1\n"})
    monkeypatch.setattr(Path, "is_symlink", lambda self: self.name == "nested")

    with pytest.raises(InvalidRepositoryPathError, match="Symbolic links"):
        save_repository_file(archive_path, edits_root, "nested/model.py", "VALUE = 2\n")


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("README.md", "docs"),
        ("settings.yaml", "config"),
        ("photo.png", "binary"),
        ("script.sh", "other"),
    ],
)
def test_language_classification_covers_supported_categories(path: str, expected: str) -> None:
    assert language_for(path) == expected


def test_python_analysis_handles_async_functions_and_syntax_errors() -> None:
    async_analysis = analyze_python("worker.py", "async def run(value):\n    return value\n")
    invalid_analysis = analyze_python("broken.py", "def broken(:\n    pass\n")

    assert async_analysis.symbols[0]["is_async"] is True
    assert invalid_analysis.tree is None
    assert invalid_analysis.symbols[0]["kind"] == "parse_error"
    assert invalid_analysis.symbols[0]["line"] == 1


def test_empty_file_list_builds_an_empty_tree() -> None:
    assert build_hierarchical_tree([]) == []


def test_file_tree_builds_sorted_folders_and_language_metadata() -> None:
    tree = build_hierarchical_tree(
        [
            {"path": "src/model.py", "language": "python", "size": 10},
            {"path": "docs/guide.md", "language": "docs", "size": 5},
            {"path": "settings.json", "language": "config", "size": 3},
            {"path": "NOTICE.custom", "size": 4},
        ],
        root_name="sample",
    )

    root = tree[0]
    assert root["name"] == "sample"
    assert root["child_count"] == 4
    assert root["descendant_count"] == 6
    assert [child["name"] for child in root["children"]] == [
        "docs",
        "src",
        "NOTICE.custom",
        "settings.json",
    ]
    docs, src, notice, settings = root["children"]
    assert docs["meta"] == "1 entries"
    assert docs["children"][0]["meta"] == "doc"
    assert src["children"][0]["meta"] == "python"
    assert notice["meta"] == "file"
    assert settings["meta"] == "config"
