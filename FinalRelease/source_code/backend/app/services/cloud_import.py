"""Post-import processing for entities downloaded from the cloud.

A synced PDF or ZIP arrives as raw bytes plus a small metadata payload: the parsed
structure never travels through the sync protocol (see docs/cloud-sync-architecture.md
§4 — parse caches are device-local). So the downloading device has to reproduce the
derived data itself, using *its own* configured parser and analyzer, exactly as if the
user had uploaded the file by hand.

Before this module existed the import path called the pypdf compatibility parser inline
and stamped ``parser="cloud-import"`` / ``content_hash=""``, which silently downgraded
every synced paper to the fallback reader even when the device had MinerU configured.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from sqlmodel import Session, select

from app.db.session import engine
from app.models.entities import PaperDocument

logger = logging.getLogger(__name__)

# Mirrors analysis_jobs/_submitted_jobs: lets the test fixture drain in-flight import
# workers before it rebinds ``engine``, so a leaked worker cannot commit into the next
# test's database (or the developer's real one once the patch is reverted).
_submit_lock = threading.Lock()
_submitted: set[str] = set()

# The parse runs in the PaperParsingService executor; we only poll for the terminal
# state. Official MinerU tasks are bounded by their own task_timeout_seconds, so this
# ceiling is a backstop against a wedged poll loop, not the real parse deadline.
_POLL_INTERVAL_SECONDS = 2.0
_POLL_CEILING_SECONDS = 60 * 60


def schedule_paper_reparse(project_id: int, public_id: str) -> None:
    """Re-derive a freshly imported paper with the device's configured parser."""

    key = f"paper:{public_id}"
    with _submit_lock:
        if key in _submitted:
            return
        _submitted.add(key)
    thread = threading.Thread(
        target=_run_tracked,
        args=(key, _reparse_paper, project_id, public_id),
        name=f"cloud-import-paper-{public_id[:8]}",
        daemon=True,
    )
    thread.start()


def _run_tracked(key: str, target, *args) -> None:
    try:
        target(*args)
    finally:
        with _submit_lock:
            _submitted.discard(key)


def _load_document(session: Session, public_id: str) -> PaperDocument | None:
    return session.exec(select(PaperDocument).where(PaperDocument.public_id == public_id)).first()


def _reparse_paper(project_id: int, public_id: str) -> None:
    from app.services.document_parsers.jobs import get_paper_parsing_service

    with Session(engine) as session:
        document = _load_document(session, public_id)
        if document is None:
            return
        source_path = document.storage_path

    try:
        service = get_paper_parsing_service()
    except Exception as exc:
        # No usable MinerU configuration on this device: keep the pypdf placeholder the
        # import already wrote, but say so instead of pretending the parse succeeded.
        _mark_failed(public_id, f"parser_unavailable: {type(exc).__name__}")
        logger.warning("cloud import paper %s: parser unavailable: %s", public_id, exc)
        return

    try:
        job = service.submit(project_id, document.filename, Path(source_path))
    except Exception as exc:
        _mark_failed(public_id, f"submit_failed: {type(exc).__name__}")
        logger.warning("cloud import paper %s: submit failed: %s", public_id, exc)
        return

    deadline = time.monotonic() + _POLL_CEILING_SECONDS
    while time.monotonic() < deadline:
        current = service.get(job.id)
        if current is None:
            _mark_failed(public_id, "job_lost")
            return
        if current.status == "succeeded":
            result = service.result(job.id)
            if result is None:
                _mark_failed(public_id, "result_missing")
                return
            _apply_result(project_id, public_id, current.parser, current.cache_key, result)
            return
        if current.status == "failed":
            _mark_failed(public_id, current.error or "parse_failed")
            logger.warning("cloud import paper %s: parse failed: %s", public_id, current.error)
            return
        time.sleep(_POLL_INTERVAL_SECONDS)
    _mark_failed(public_id, "parse_timeout")


def _mark_failed(public_id: str, reason: str) -> None:
    """Record that the device could not reproduce the origin's parse.

    The pypdf placeholder written at import time stays in place so the reader still has
    text; ``parse_status`` is what tells the UI the content is degraded.
    """

    with Session(engine) as session:
        document = _load_document(session, public_id)
        if document is None:
            return
        document.parse_status = "failed"
        document.parser_version = f"{document.parser_version}|{reason}"[:128]
        session.add(document)
        session.commit()


def _apply_result(
    project_id: int,
    public_id: str,
    parser_name: str,
    cache_key: str,
    result: dict,
) -> None:
    """Replace the placeholder structure with the real parse.

    ``content_hash`` is the parse cache key: without it ``markdown_for_cache`` cannot find
    the MinerU markdown/asset archive, and the reader falls back to synthesized markdown.
    """

    with Session(engine) as session:
        document = _load_document(session, public_id)
        if document is None:
            return
        document.title = str(result.get("title", document.title))
        document.abstract = str(result.get("abstract", document.abstract))
        document.parser = str(result.get("parser", parser_name))
        document.parser_version = str(result.get("parser_version", "unknown"))
        document.parse_status = "succeeded"
        document.content_hash = cache_key
        document.sections_json = list(result.get("sections", []))
        document.paragraphs_json = list(result.get("paragraphs", []))
        document.pages_json = list(result.get("pages", []))
        session.add(document)
        session.commit()

    # The retrieval index is keyed by content_hash, so it must be rebuilt only after the
    # real parse lands — indexing the placeholder would pin a generation we then discard.
    try:
        from app.services.rag import refresh_project_indexes

        refresh_project_indexes(project_id, ("paper",))
    except Exception as exc:
        logger.warning("cloud import paper %s: index refresh failed: %s", public_id, exc)


def schedule_repository_analysis(project_id: int, revision: int) -> None:
    """Run full code analysis on a freshly imported repository archive.

    ``scan_code_archive`` (used inline at import time so the file tree renders immediately)
    returns empty ``symbols`` / ``imports`` / ``pytorch_candidates``. Those feed the code
    retrieval index and the static trace candidates, so without this the downloading device
    has a browsable tree but no searchable code and no static suggestions.

    A synced diagram blob may overwrite the derived graph afterwards; that is intentional
    and matches ``import_cloud_diagram`` — the origin's Agent-refined diagram wins over a
    locally recomputed one, while the symbol tables here are what the index needs.
    """

    key = f"repo:{project_id}:{revision}"
    with _submit_lock:
        if key in _submitted:
            return
        _submitted.add(key)
    thread = threading.Thread(
        target=_run_tracked,
        args=(key, _analyze_repository, project_id, revision),
        name=f"cloud-import-repo-{project_id}",
        daemon=True,
    )
    thread.start()


def _analyze_repository(project_id: int, revision: int) -> None:
    try:
        from app.services.analysis_jobs import enqueue_repository_analysis

        enqueue_repository_analysis(project_id, ["all"], f"cloud-import-{revision}")
    except Exception as exc:
        # Best-effort, exactly like the upload path's _trigger_auto_trace: the tree is
        # already usable and the user can re-run analysis from the UI.
        logger.warning(
            "cloud import repo (project %s): analysis enqueue failed: %s", project_id, exc
        )
