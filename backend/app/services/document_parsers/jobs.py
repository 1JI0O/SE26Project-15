import hashlib
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.services.document_parsers.base import DocumentParser, ParseOutcome
from app.services.document_parsers.factory import create_mineru_parser


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class PaperParseJob:
    id: str
    project_id: int
    filename: str
    source_path: str
    parser: str
    status: str
    created_at: str
    updated_at: str
    cache_key: str = ""
    external_task_id: str | None = None
    error: str | None = None
    cached: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "filename": self.filename,
            "parser": self.parser,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "external_task_id": self.external_task_id,
            "error": self.error,
            "cached": self.cached,
        }


class PaperParsingService:
    def __init__(
        self,
        parser: DocumentParser | None = None,
        *,
        root: Path | None = None,
        max_workers: int = 1,
    ) -> None:
        self.parser = parser or create_mineru_parser()
        self.root = root or Path(os.getenv("TRACELAB_PAPER_JOB_ROOT", "./data/paper-jobs"))
        self.jobs_root = self.root / "jobs"
        self.cache_root = self.root / "cache"
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="paper-parse"
        )
        self._lock = threading.Lock()

    def submit(self, project_id: int, filename: str, source_path: Path) -> PaperParseJob:
        now = _now()
        job = PaperParseJob(
            id=f"paper-{uuid4().hex}",
            project_id=project_id,
            filename=filename,
            source_path=str(source_path),
            parser=self.parser.name,
            status="queued",
            created_at=now,
            updated_at=now,
        )
        self._save_job(job)
        self._executor.submit(self._run, job.id)
        return job

    def get(self, job_id: str) -> PaperParseJob | None:
        path = self.jobs_root / f"{job_id}.json"
        if not path.exists():
            return None
        try:
            return PaperParseJob(**json.loads(path.read_text(encoding="utf-8")))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def result(self, job_id: str) -> dict[str, Any] | None:
        job = self.get(job_id)
        if job is None or job.status != "succeeded" or not job.cache_key:
            return None
        path = self.cache_root / f"{job.cache_key}.normalized.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def cached_result_for_source(self, source_path: Path) -> dict[str, Any] | None:
        if not source_path.exists():
            return None
        path = self.cache_root / f"{self._cache_key(source_path)}.normalized.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _run(self, job_id: str) -> None:
        job = self.get(job_id)
        if job is None:
            return
        try:
            source_path = Path(job.source_path)
            cache_key = self._cache_key(source_path)
            job.cache_key = cache_key
            normalized_path = self.cache_root / f"{cache_key}.normalized.json"
            if normalized_path.exists():
                job.status = "succeeded"
                job.cached = True
                job.updated_at = _now()
                self._save_job(job)
                return

            job.status = "running"
            job.updated_at = _now()
            self._save_job(job)
            outcome = self.parser.parse(source_path)
            job.external_task_id = outcome.external_task_id
            self._save_outcome(cache_key, outcome)
            job.status = "succeeded"
        except Exception as exc:
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}"[:1000]
        job.updated_at = _now()
        self._save_job(job)

    def _cache_key(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        cache_namespace = getattr(self.parser, "cache_namespace", self.parser.name)
        digest.update(str(cache_namespace).encode())
        return digest.hexdigest()

    def _save_outcome(self, cache_key: str, outcome: ParseOutcome) -> None:
        normalized_path = self.cache_root / f"{cache_key}.normalized.json"
        raw_json_path = self.cache_root / f"{cache_key}.raw.json"
        self._atomic_json_write(normalized_path, outcome.document.to_dict())
        self._atomic_json_write(raw_json_path, outcome.raw_payload)
        if outcome.raw_archive is not None:
            raw_archive_path = self.cache_root / f"{cache_key}.raw.zip"
            temporary = raw_archive_path.with_suffix(".zip.tmp")
            temporary.write_bytes(outcome.raw_archive)
            temporary.replace(raw_archive_path)

    def _save_job(self, job: PaperParseJob) -> None:
        with self._lock:
            self._atomic_json_write(self.jobs_root / f"{job.id}.json", asdict(job))

    @staticmethod
    def _atomic_json_write(path: Path, payload: Any) -> None:
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)


_paper_parsing_service: PaperParsingService | None = None


def get_paper_parsing_service() -> PaperParsingService:
    global _paper_parsing_service
    if _paper_parsing_service is None:
        _paper_parsing_service = PaperParsingService()
    return _paper_parsing_service


def reset_paper_parsing_service() -> None:
    """Apply new parser settings to future jobs without interrupting active jobs."""

    global _paper_parsing_service
    _paper_parsing_service = None
