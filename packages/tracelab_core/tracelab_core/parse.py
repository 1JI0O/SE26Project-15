"""Paper PDF parsing into `.tracelab/papers/`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tracelab_core.backend_path import ensure_backend_path
from tracelab_core.paper_export import export_paper_reader_artifacts
from tracelab_core.progress import emit_progress
from tracelab_core.workspace import TraceLabPaths, append_job_log, write_json


def parse_paper(
    paths: TraceLabPaths,
    mineru_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ensure_backend_path()
    if not paths.source_pdf.is_file():
        raise FileNotFoundError(f"Missing source PDF: {paths.source_pdf}")

    payload: dict[str, Any]
    raw_archive: bytes | None = None
    parser_name = "pypdf-fallback"
    source = "normalized-fallback"
    mineru_error: str | None = None

    if mineru_config and mineru_config.get("enabled"):
        emit_progress(
            "parse",
            f"MinerU ({mineru_config.get('provider', 'official')} / {mineru_config.get('model', 'pipeline')})",
        )
        try:
            payload, raw_archive = _parse_with_mineru(paths.source_pdf, mineru_config)
            parser_name = payload.get("parser", "mineru")
            source = "mineru-markdown"
        except Exception as exc:
            mineru_error = str(exc)
            append_job_log(
                paths,
                "parse-warning",
                {"message": f"MinerU failed, using pypdf fallback: {exc}"},
            )
            emit_progress("parse", f"MinerU failed, pypdf fallback: {exc}")
            payload = _parse_with_pypdf(paths.source_pdf)
            source = "normalized-fallback"
    else:
        emit_progress("parse", "Parsing with pypdf fallback")
        payload = _parse_with_pypdf(paths.source_pdf)
        source = "normalized-fallback"

    write_json(paths.normalized_json, payload)
    emit_progress("parse", "Exporting Markdown + assets for reader")
    paper_document = export_paper_reader_artifacts(
        paths,
        payload,
        raw_archive=raw_archive,
        source=source,
    )
    append_job_log(
        paths,
        "parse",
        {
            "parser": parser_name,
            "title": payload.get("title"),
            "pages": len(payload.get("pages", [])),
            "markdown_source": paper_document.get("source"),
            "blocks": len(paper_document.get("blocks") or []),
            "mineru_error": mineru_error,
        },
    )
    result = {
        "parser": parser_name,
        "normalized_path": str(paths.normalized_json),
        "document_md": str(paths.document_md),
        "paper_document_path": str(paths.paper_document_json),
        "markdown_source": paper_document.get("source"),
        "document": payload,
    }
    if mineru_error:
        result["mineru_error"] = mineru_error
    return result


def _parse_with_pypdf(pdf_path: Path) -> dict[str, Any]:
    from app.services.paper_parser import parse_pdf

    return parse_pdf(pdf_path)


def _parse_with_mineru(
    pdf_path: Path,
    mineru_config: dict[str, Any],
) -> tuple[dict[str, Any], bytes | None]:
    from app.services.document_parsers.mineru import MinerUClient, MinerUParser, MinerUSettings
    from app.services.document_parsers.mineru_official import (
        OfficialMinerUClient,
        OfficialMinerUSettings,
    )

    provider = mineru_config.get("provider", "official")
    if provider == "official":
        client = OfficialMinerUClient(
            OfficialMinerUSettings(
                base_url=str(
                    mineru_config.get("base_url") or "https://mineru.net/api/v4"
                ).rstrip("/"),
                token=str(mineru_config.get("api_token", "")),
                model=str(
                    mineru_config.get("model")
                    or mineru_config.get("official_api_model")
                    or "vlm"
                ),
                language=str(mineru_config.get("language", "en")),
                ocr=bool(mineru_config.get("ocr", True)),
                formula_enable=bool(mineru_config.get("formula_enable", True)),
                table_enable=bool(mineru_config.get("table_enable", True)),
                request_timeout_seconds=int(mineru_config.get("request_timeout_seconds", 120)),
                request_retries=int(mineru_config.get("request_retries", 2)),
                task_timeout_seconds=int(mineru_config.get("task_timeout_seconds", 1800)),
                poll_interval_seconds=float(mineru_config.get("poll_interval_seconds", 2.0)),
            )
        )
    else:
        client = MinerUClient(
            MinerUSettings(
                base_url=str(mineru_config.get("base_url", "http://127.0.0.1:8001")),
                backend=str(mineru_config.get("backend", "pipeline")),
                language=str(mineru_config.get("language", "en")),
                parse_method=str(mineru_config.get("parse_method", "auto")),
                request_timeout_seconds=int(mineru_config.get("request_timeout_seconds", 120)),
                task_timeout_seconds=int(mineru_config.get("task_timeout_seconds", 1800)),
                poll_interval_seconds=float(mineru_config.get("poll_interval_seconds", 2.0)),
            )
        )
    parser = MinerUParser(client)
    outcome = parser.parse(pdf_path)
    return outcome.document.to_dict(), outcome.raw_archive
