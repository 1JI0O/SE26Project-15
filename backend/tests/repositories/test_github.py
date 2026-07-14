import pytest

from app.integrations.github import GitHubImportError, parse_github_repository_url


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
