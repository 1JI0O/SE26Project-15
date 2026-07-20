import mimetypes

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlmodel import Session, select

from app.api.routes.helpers import parse_workspace_project_id
from app.api.routes.projects import get_project_or_404
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
from app.services.paper_markdown import build_fallback_markdown, extract_markdown_sections
from app.services.paper_parser import parse_pdf
from app.services.workspace_placeholder import workspace_payload
from app.storage.file_store import save_upload

router = APIRouter(prefix="/projects/{project_id}", tags=["papers"])


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
    parsed = parse_pdf(storage_path)
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
    project_id: int,
    job_id: str,
    session: Session = Depends(get_session),
    service: PaperParsingService = Depends(get_paper_parsing_service),
) -> PaperParseJobRead:
    get_project_or_404(project_id, session)
    job = service.get(job_id)
    if job is None or job.project_id != project_id:
        raise HTTPException(status_code=404, detail="Paper parse job not found")
    document = _document_for_job(job, service, session) if job.status == "succeeded" else None
    return _job_read(job, document)


@router.get("/paper-jobs/{job_id}/result", response_model=PaperParseResultRead)
def read_paper_parse_result(
    project_id: int,
    job_id: str,
    session: Session = Depends(get_session),
    service: PaperParsingService = Depends(get_paper_parsing_service),
) -> PaperParseResultRead:
    get_project_or_404(project_id, session)
    job = service.get(job_id)
    if job is None or job.project_id != project_id:
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
    document = session.exec(
        select(PaperDocument)
        .where(PaperDocument.project_id == project_id)
        .order_by(PaperDocument.created_at.desc(), PaperDocument.id.desc())
    ).first()
    if document is None:
        raise HTTPException(status_code=404, detail="Paper has not been uploaded or parsed")

    mineru_markdown = service.markdown_for_cache(document.content_hash)
    markdown = mineru_markdown or build_fallback_markdown(document)
    return WorkspacePaperDocument(
        document_id=document.id or 0,
        filename=document.filename,
        title=document.title,
        markdown=markdown,
        sections=extract_markdown_sections(markdown, document.sections_json),
        asset_base_url=f"/projects/{project_id}/paper/assets",
        parser=document.parser,
        parser_version=document.parser_version,
        source="mineru-markdown" if mineru_markdown else "normalized-fallback",
    )


@router.get("/paper/assets/{asset_path:path}")
def read_paper_asset(
    project_id: int,
    asset_path: str,
    session: Session = Depends(get_session),
    service: PaperParsingService = Depends(get_paper_parsing_service),
) -> Response:
    get_project_or_404(project_id, session)
    document = session.exec(
        select(PaperDocument)
        .where(PaperDocument.project_id == project_id)
        .order_by(PaperDocument.created_at.desc(), PaperDocument.id.desc())
    ).first()
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
