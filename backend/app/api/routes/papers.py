from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlmodel import Session, select

from app.api.routes.helpers import parse_workspace_project_id
from app.api.routes.projects import get_project_or_404
from app.db.session import get_session
from app.models.entities import PaperDocument
from app.schemas.papers import PaperDocumentRead, WorkspacePaperPage
from app.services import workspace_service
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
        created_at=document.created_at,
    )


@router.post("/paper", response_model=PaperDocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_paper(
    project_id: int,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> PaperDocumentRead:
    get_project_or_404(project_id, session)
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
        sections_json=parsed["sections"],
        paragraphs_json=parsed["paragraphs"],
    )
    session.add(document)
    session.commit()
    session.refresh(document)
    return _paper_read(document)


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
