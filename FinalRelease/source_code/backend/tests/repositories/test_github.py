from pathlib import Path

import pytest

from app.integrations.github import GitHubImportError, importer, parse_github_repository_url


def test_parse_github_repository_url_accepts_canonical_urls() -> None:
    repository = parse_github_repository_url("https://github.com/pytorch/vision.git")
    assert repository.owner == "pytorch"
    assert repository.name == "vision"
    assert repository.clone_url == "https://github.com/pytorch/vision.git"


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/pytorch/vision",
        "https://example.com/pytorch/vision",
        "https://github.com/pytorch/vision/issues",
        "https://user:token@github.com/pytorch/vision",
        "https://github.com/pytorch/vision?tab=readme",
    ],
)
def test_parse_github_repository_url_rejects_unsafe_or_non_repository_urls(url: str) -> None:
    with pytest.raises(GitHubImportError):
        parse_github_repository_url(url)


def test_import_archive_uses_absolute_output_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(importer.settings, "upload_root", str(tmp_path / "uploads"))
    commands: list[list[str]] = []

    def fake_run_git(arguments: list[str], _timeout: int) -> None:
        commands.append(arguments)
        output = next(
            (item.removeprefix("--output=") for item in arguments if item.startswith("--output=")),
            None,
        )
        if output is not None:
            assert Path(output).is_absolute()
            Path(output).write_bytes(b"zip")

    monkeypatch.setattr(importer, "_run_git", fake_run_git)
    archive, filename = importer.import_github_archive(
        7,
        "https://github.com/octocat/Hello-World",
    )

    assert archive.exists()
    assert filename == "octocat-Hello-World.zip"
    assert len(commands) == 2
