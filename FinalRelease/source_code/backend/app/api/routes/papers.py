import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from app.api.routes.helpers import parse_workspace_project_id
from app.api.routes.projects import get_project_or_404
from app.core.config import settings
from app.db.session import get_session
from app.models.entities import PaperDocument
from app.schemas.papers import (
    PaperDocumentRead,
    PaperParseJobRead,
    PaperParseResultRead,
    WorkspacePaperDocument,
    WorkspacePaperPage,
)
from app.services import workspace_service
from app.services.document_parsers.jobs import (
    PaperParseJob,
    PaperParsingService,
    get_paper_parsing_service,
)
from app.services.local_sync import paper_payload, record_local_operation
from app.services.paper_markdown import (
    build_fallback_markdown,
    extract_markdown_sections,
    inject_block_anchors,
)
from app.services.paper_parser import PdfParseError, parse_pdf
from app.services.workspace_placeholder import workspace_payload
from app.storage.file_store import save_upload

router = APIRouter(prefix="/projects/{project_id}", tags=["papers"])


def _trigger_auto_trace(project_id: int) -> None:
    """Best-effort: refresh the paper retrieval index, then start background trace.

    The index is built before the trace job is enqueued so the agent's first
    ``semantic_search_paper`` call already has a corpus; if it is not ready, the tool falls
    back to paging and the run still completes.
    """

    from app.services.rag import refresh_project_indexes
    from app.services.tracing.coordinator import maybe_start_trace

    refresh_project_indexes(project_id, ("paper",))
    maybe_start_trace(project_id)


def _paper_read(document: PaperDocument) -> PaperDocumentRead:
    return PaperDocumentRead(
        id=document.id or 0,
        project_id=document.project_id,
        filename=document.filename,
        title=document.title,
        abstract=document.abstract,
        sections=document.sections_json,
        paragraphs=document.paragraphs_json,
        parser=document.parser,
        parser_version=document.parser_version,
        parse_status=document.parse_status,
        content_hash=document.content_hash,
        created_at=document.created_at,
    )


def _latest_paper(project_id: int, session: Session) -> PaperDocument | None:
    return session.exec(
        select(PaperDocument)
        .where(PaperDocument.project_id == project_id)
        .order_by(PaperDocument.created_at.desc(), PaperDocument.id.desc())
    ).first()


def _stored_pdf_path(document: PaperDocument) -> Path | None:
    """Resolve a document's PDF on disk, refusing anything outside the upload root.

    ``storage_path`` is recorded at upload time and could otherwise be an absolute path
    left behind by a restored database or an earlier install, so it is re-checked
    against the configured root before any bytes are served.
    """

    if not document.storage_path:
        return None
    root = Path(settings.upload_root).resolve()
    try:
        path = Path(document.storage_path).resolve()
    except OSError:
        return None
    if not path.is_relative_to(root) or not path.is_file():
        return None
    return path


def _document_for_job(
    job: PaperParseJob,
    service: PaperParsingService,
    session: Session,
) -> PaperDocument | None:
    existing = session.exec(
        select(PaperDocument).where(PaperDocument.storage_path == job.source_path)
    ).first()
    if existing is not None:
        return existing
    result = service.result(job.id)
    if result is None:
        return None
    document = PaperDocument(
        project_id=job.project_id,
        filename=job.filename,
        storage_path=job.source_path,
        title=str(result.get("title", "")),
        abstract=str(result.get("abstract", "")),
        parser=str(result.get("parser", job.parser)),
        parser_version=str(result.get("parser_version", "unknown")),
        parse_status="succeeded",
        content_hash=job.cache_key,
        sections_json=list(result.get("sections", [])),
        paragraphs_json=list(result.get("paragraphs", [])),
        pages_json=list(result.get("pages", [])),
    )
    session.add(document)
    project = get_project_or_404(job.project_id, session)
    session.flush()
    record_local_operation(
        session,
        project,
        "paper_document",
        document.public_id,
        paper_payload(project, document),
        base_version=0,
    )
    session.commit()
    session.refresh(document)
    _trigger_auto_trace(job.project_id)
    return document


def _job_read(job: PaperParseJob, document: PaperDocument | None = None) -> PaperParseJobRead:
    return PaperParseJobRead(
        **job.public_dict(),
        document_id=document.id if document is not None else None,
    )


@router.post("/paper", response_model=PaperDocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_paper(
    project_id: int,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> PaperDocumentRead:
    project = get_project_or_404(project_id, session)
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    storage_path = save_upload(project_id, "paper", file)
    try:
        parsed = parse_pdf(storage_path)
    except PdfParseError as exc:
        # The extension check above only looks at the filename, so an unreadable or
        # truncated file first fails here. That is bad client input, not a server fault.
        Path(storage_path).unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    document = PaperDocument(
        project_id=project_id,
        filename=file.filename,
        storage_path=str(storage_path),
        title=parsed["title"],
        abstract=parsed["abstract"],
        parser=str(parsed.get("parser", "pypdf")),
        parser_version=str(parsed.get("parser_version", "compat")),
        pages_json=list(parsed.get("pages", [])),
        sections_json=parsed["sections"],
        paragraphs_json=parsed["paragraphs"],
    )
    session.add(document)
    session.flush()
    record_local_operation(
        session,
        project,
        "paper_document",
        document.public_id,
        paper_payload(project, document),
        base_version=0,
    )
    session.commit()
    session.refresh(document)
    _trigger_auto_trace(project_id)
    return _paper_read(document)


@router.post(
    "/paper-jobs",
    response_model=PaperParseJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_paper_parse_job(
    project_id: int,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    service: PaperParsingService = Depends(get_paper_parsing_service),
) -> PaperParseJobRead:
    get_project_or_404(project_id, session)
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    storage_path = save_upload(project_id, "paper", file)
    if storage_path.stat().st_size == 0:
        storage_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="PDF file is empty")
    job = service.submit(project_id, file.filename, storage_path)
    return _job_read(job)


@router.get("/paper-jobs/{job_id}", response_model=PaperParseJobRead)
def read_paper_parse_job(
    project_id: str,
    job_id: str,
    session: Session = Depends(get_session),
    service: PaperParsingService = Depends(get_paper_parsing_service),
) -> PaperParseJobRead:
    # Accept str so a stale poll with a non-numeric id (e.g. the client's route id became NaN
    # after navigating away mid-parse) is a clean 404, not a 422 request-validation error.
    numeric_id = parse_workspace_project_id(project_id)
    if numeric_id is None:
        raise HTTPException(status_code=404, detail="Paper parse job not found")
    get_project_or_404(numeric_id, session)
    job = service.get(job_id)
    if job is None or job.project_id != numeric_id:
        raise HTTPException(status_code=404, detail="Paper parse job not found")
    document = _document_for_job(job, service, session) if job.status == "succeeded" else None
    return _job_read(job, document)


@router.get("/paper-jobs/{job_id}/result", response_model=PaperParseResultRead)
def read_paper_parse_result(
    project_id: str,
    job_id: str,
    session: Session = Depends(get_session),
    service: PaperParsingService = Depends(get_paper_parsing_service),
) -> PaperParseResultRead:
    numeric_id = parse_workspace_project_id(project_id)
    if numeric_id is None:
        raise HTTPException(status_code=404, detail="Paper parse job not found")
    get_project_or_404(numeric_id, session)
    job = service.get(job_id)
    if job is None or job.project_id != numeric_id:
        raise HTTPException(status_code=404, detail="Paper parse job not found")
    if job.status != "succeeded":
        raise HTTPException(status_code=409, detail=f"Paper parse job is {job.status}")
    result = service.result(job.id)
    document = _document_for_job(job, service, session)
    if result is None or document is None:
        raise HTTPException(status_code=500, detail="Paper parse result is unavailable")
    return PaperParseResultRead(
        job=_job_read(job, document),
        document=_paper_read(document),
        parser=str(result.get("parser", job.parser)),
        parser_version=str(result.get("parser_version", "unknown")),
        pages=list(result.get("pages", [])),
    )


@router.get("/paper", response_model=PaperDocumentRead)
def read_latest_paper(
    project_id: int,
    session: Session = Depends(get_session),
) -> PaperDocumentRead:
    get_project_or_404(project_id, session)
    statement = (
        select(PaperDocument)
        .where(PaperDocument.project_id == project_id)
        .order_by(PaperDocument.created_at.desc(), PaperDocument.id.desc())
    )
    document = session.exec(statement).first()
    if document is None:
        raise HTTPException(status_code=404, detail="Paper has not been uploaded")
    return _paper_read(document)


@router.get("/workspace/paper-pages", response_model=list[WorkspacePaperPage])
def read_paper_pages(
    project_id: str,
    session: Session = Depends(get_session),
) -> list[WorkspacePaperPage]:
    numeric_id = parse_workspace_project_id(project_id)
    if numeric_id is None:
        payload = workspace_payload(project_id)
        return [WorkspacePaperPage(**item) for item in payload["paper_pages"]]

    get_project_or_404(numeric_id, session)
    pages = workspace_service.get_paper_pages(session, numeric_id)
    if not pages:
        raise HTTPException(status_code=404, detail="Paper has not been uploaded or parsed")
    return [WorkspacePaperPage(**item) for item in pages]


@router.get("/workspace/paper-document", response_model=WorkspacePaperDocument)
def read_workspace_paper_document(
    project_id: int,
    session: Session = Depends(get_session),
    service: PaperParsingService = Depends(get_paper_parsing_service),
) -> WorkspacePaperDocument:
    get_project_or_404(project_id, session)
    document = _latest_paper(project_id, session)
    if document is None:
        raise HTTPException(status_code=404, detail="Paper has not been uploaded or parsed")

    mineru_markdown = service.markdown_for_cache(document.content_hash)
    markdown = mineru_markdown or build_fallback_markdown(document)
    anchor_pages = document.pages_json or [{"blocks": document.paragraphs_json}]
    markdown, blocks = inject_block_anchors(markdown, anchor_pages)
    return WorkspacePaperDocument(
        document_id=document.id or 0,
        filename=document.filename,
        title=document.title,
        markdown=markdown,
        sections=extract_markdown_sections(markdown, document.sections_json),
        asset_base_url=f"/projects/{project_id}/paper/assets",
        # Absent when the upload predates PDF retention or the file has since been
        # removed; the reader then offers markdown only.
        pdf_url=(
            f"/projects/{project_id}/paper/file"
            if _stored_pdf_path(document) is not None
            else None
        ),
        parser=document.parser,
        parser_version=document.parser_version,
        source="mineru-markdown" if mineru_markdown else "normalized-fallback",
        blocks=blocks,
    )


@router.get("/paper/file")
def read_paper_file(
    project_id: int,
    session: Session = Depends(get_session),
) -> FileResponse:
    """Stream the original uploaded PDF.

    The reader overlays trace highlights on the real page rather than on rendered
    markdown, so it needs the source document itself — MinerU's markdown is a
    reading-oriented approximation and its line breaks do not correspond to the PDF's.
    """

    get_project_or_404(project_id, session)
    document = _latest_paper(project_id, session)
    if document is None:
        raise HTTPException(status_code=404, detail="Paper has not been uploaded or parsed")
    path = _stored_pdf_path(document)
    if path is None:
        raise HTTPException(status_code=404, detail="Original PDF file is unavailable")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=document.filename or path.name,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get("/paper/assets/{asset_path:path}")
def read_paper_asset(
    project_id: int,
    asset_path: str,
    session: Session = Depends(get_session),
    service: PaperParsingService = Depends(get_paper_parsing_service),
) -> Response:
    get_project_or_404(project_id, session)
    document = _latest_paper(project_id, session)
    if document is None:
        raise HTTPException(status_code=404, detail="Paper has not been uploaded or parsed")
    try:
        asset = service.asset_for_cache(document.content_hash, asset_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if asset is None:
        raise HTTPException(status_code=404, detail="Paper asset is unavailable")
    content, filename = asset
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )
