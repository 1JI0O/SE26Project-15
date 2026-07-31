import zipfile
from pathlib import Path

import pytest

from app.services.code_analysis.editor import (
    FileNotEditableError,
    FileTooLargeError,
    InvalidRepositoryPathError,
    RepositoryFileNotFoundError,
    read_repository_file,
    save_repository_file,
)


def _repository(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("repo/.gitignore", "ignored.py\n")
        archive.writestr("repo/model.py", "VALUE = 1\n")
        archive.writestr("repo/ignored.py", "SECRET = True\n")
        archive.writestr("repo/data.txt", b"text\x00binary")


def test_read_and_save_are_limited_to_allowed_repository_paths(tmp_path: Path) -> None:
    archive_path = tmp_path / "repository.zip"
    edits_root = tmp_path / "edits"
    _repository(archive_path)

    assert read_repository_file(archive_path, "model.py") == "VALUE = 1\n"
    save_repository_file(archive_path, edits_root, "model.py", "VALUE = 2\n")
    assert read_repository_file(archive_path, "model.py", edits_root=edits_root) == "VALUE = 2\n"

    with pytest.raises(InvalidRepositoryPathError):
        save_repository_file(archive_path, edits_root, "../outside.py", "bad\n")
    with pytest.raises(InvalidRepositoryPathError):
        read_repository_file(archive_path, "/model.py")
    with pytest.raises(RepositoryFileNotFoundError):
        read_repository_file(archive_path, "ignored.py")
    with pytest.raises(FileNotEditableError):
        read_repository_file(archive_path, "data.txt")


def test_save_rejects_oversized_utf8_content(tmp_path: Path) -> None:
    archive_path = tmp_path / "repository.zip"
    _repository(archive_path)

    with pytest.raises(FileTooLargeError):
        save_repository_file(archive_path, tmp_path / "edits", "model.py", "x" * 512_001)
