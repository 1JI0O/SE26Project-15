from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlmodel import Session, select

from app.api.routes.projects import get_project_or_404
from app.db.session import get_session
from app.models.entities import CodeRepository, PaperDocument
from app.schemas import CodeRepositoryRead, PaperDocumentRead
from app.services.code_analyzer import analyze_code_archive
from app.services.paper_parser import parse_pdf
from app.storage.file_store import save_upload

router = APIRouter(prefix="/projects/{project_id}", tags=["artifacts"])


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


def _code_read(repository: CodeRepository) -> CodeRepositoryRead:
    return CodeRepositoryRead(
        id=repository.id or 0,
        project_id=repository.project_id,
        filename=repository.filename,
        file_tree=repository.file_tree_json,
        symbols=repository.symbols_json,
        imports=repository.imports_json,
        pytorch_candidates=repository.pytorch_candidates_json,
        created_at=repository.created_at,
    )


@router.post("/paper", response_model=PaperDocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_paper(
    project_id: int,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> PaperDocumentRead:
    get_project_or_404(project_id, session)
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported in iteration 1")

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


@router.post("/code", response_model=CodeRepositoryRead, status_code=status.HTTP_201_CREATED)
async def upload_code(
    project_id: int,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> CodeRepositoryRead:
    get_project_or_404(project_id, session)
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(
            status_code=400,
            detail="Only ZIP archives are supported in iteration 1",
        )

    storage_path = save_upload(project_id, "code", file)
    analyzed = analyze_code_archive(storage_path)
    repository = CodeRepository(
        project_id=project_id,
        filename=file.filename,
        storage_path=str(storage_path),
        file_tree_json=analyzed["file_tree"],
        symbols_json=analyzed["symbols"],
        imports_json=analyzed["imports"],
        pytorch_candidates_json=analyzed["pytorch_candidates"],
    )
    session.add(repository)
    session.commit()
    session.refresh(repository)
    return _code_read(repository)


@router.get("/code", response_model=CodeRepositoryRead)
def read_latest_code(
    project_id: int,
    session: Session = Depends(get_session),
) -> CodeRepositoryRead:
    get_project_or_404(project_id, session)
    statement = (
        select(CodeRepository)
        .where(CodeRepository.project_id == project_id)
        .order_by(CodeRepository.created_at.desc(), CodeRepository.id.desc())
    )
    repository = session.exec(statement).first()
    if repository is None:
        raise HTTPException(status_code=404, detail="Code archive has not been uploaded")
    return _code_read(repository)
