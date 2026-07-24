import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from app.core.config import settings

_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


class GitHubImportError(ValueError):
    pass


@dataclass(frozen=True)
class GitHubRepository:
    owner: str
    name: str

    @property
    def clone_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.name}.git"


def parse_github_repository_url(url: str) -> GitHubRepository:
    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or parsed.hostname not in {"github.com", "www.github.com"}:
        raise GitHubImportError("Only HTTPS github.com repository URLs are supported")
    if parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment:
        raise GitHubImportError("GitHub repository URL must not contain credentials or options")
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) != 2:
        raise GitHubImportError("GitHub URL must identify exactly one owner and repository")
    owner, repository = parts
    name = repository[:-4] if repository.endswith(".git") else repository
    valid_owner = bool(owner and _NAME_PATTERN.fullmatch(owner))
    valid_name = bool(name and _NAME_PATTERN.fullmatch(name))
    if not valid_owner or not valid_name:
        raise GitHubImportError("GitHub owner or repository name contains unsupported characters")
    return GitHubRepository(owner=owner, name=name)


def _run_git(arguments: list[str], timeout: int) -> None:
    try:
        subprocess.run(
            ["git", *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise GitHubImportError("Git is required for GitHub repository import") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitHubImportError("GitHub repository import timed out") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "git command failed").strip().splitlines()[-1]
        raise GitHubImportError(f"GitHub repository import failed: {detail}") from exc


def import_github_archive(project_id: int, url: str) -> tuple[Path, str]:
    repository = parse_github_repository_url(url)
    destination = Path(settings.upload_root) / f"project-{project_id}" / "code"
    destination.mkdir(parents=True, exist_ok=True)
    archive_path = (destination / f"{uuid4().hex}.zip").resolve()
    timeout = settings.github_clone_timeout_seconds
    work_root = Path(tempfile.mkdtemp(prefix="tracelab-github-"))
    checkout = work_root / repository.name
    try:
        _run_git(
            [
                "clone",
                "--depth",
                "1",
                "--filter=blob:none",
                "--no-tags",
                "--",
                repository.clone_url,
                str(checkout),
            ],
            timeout,
        )
        _run_git(
            [
                "-C",
                str(checkout),
                "archive",
                "--format=zip",
                f"--prefix={repository.name}/",
                f"--output={archive_path}",
                "HEAD",
            ],
            timeout,
        )
    except Exception:
        archive_path.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(work_root, ignore_errors=True)
    return archive_path, f"{repository.owner}-{repository.name}.zip"
