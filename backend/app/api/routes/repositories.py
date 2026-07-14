import zipfile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlmodel import Session, select

from app.api.routes.helpers import parse_workspace_project_id
from app.api.routes.projects import get_project_or_404
from app.db.session import get_session
from app.integrations.github import GitHubImportError, import_github_archive
from app.models.entities import CodeRepository
from app.schemas.repositories import (
    CodeAnalysisRead,
    CodeRepositoryRead,
    GitHubRepositoryImport,
    WorkspaceCodeFileRead,
    WorkspaceCodeFileSaveResult,
    WorkspaceCodeFileUpdate,
    WorkspaceCodeTreeNode,
    WorkspaceTensorFlowRead,
)
from app.services import workspace_service
from app.services.code_analysis.archive import InvalidCodeArchiveError
from app.services.code_analysis.editor import (
    FileAccessError,
    FileNotEditableError,
    FileTooLargeError,
    InvalidRepositoryPathError,
    RepositoryFileNotFoundError,
)
from app.services.code_analyzer import analyze_code_archive, is_editor_readable_file
from app.services.workspace_placeholder import (
    code_file_payload,
    tensor_flow_payload,
    workspace_payload,
)
from app.storage.file_store import save_upload

router = APIRouter(prefix="/projects/{project_id}", tags=["repositories"])


def _code_read(
    repository: CodeRepository,
    analysis: dict | None = None,
) -> CodeRepositoryRead:
    analysis = analysis or analyze_code_archive(repository.storage_path)
    return CodeRepositoryRead(
        id=repository.id or 0,
        project_id=repository.project_id,
        filename=repository.filename,
        file_tree=repository.file_tree_json,
        symbols=analysis["symbols"],
        imports=analysis["imports"],
        calls=analysis["calls"],
        pytorch_candidates=analysis["pytorch_candidates"],
        tensor_graph=analysis["tensor_graph"],
        summary=analysis["summary"],
        created_at=repository.created_at,
    )


def _store_repository(
    session: Session,
    project_id: int,
    filename: str,
    storage_path: str,
    analysis: dict,
) -> CodeRepository:
    repository = CodeRepository(
        project_id=project_id,
        filename=filename,
        storage_path=storage_path,
        file_tree_json=analysis["file_tree"],
        symbols_json=analysis["symbols"],
        imports_json=analysis["imports"],
        pytorch_candidates_json=analysis["pytorch_candidates"],
    )
    session.add(repository)
    session.commit()
    session.refresh(repository)
    return repository


@router.post("/code", response_model=CodeRepositoryRead, status_code=status.HTTP_201_CREATED)
async def upload_code(
    project_id: int,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> CodeRepositoryRead:
    get_project_or_404(project_id, session)
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only ZIP archives are supported")

    storage_path = save_upload(project_id, "code", file)
    try:
        analyzed = analyze_code_archive(storage_path)
    except (zipfile.BadZipFile, InvalidCodeArchiveError) as exc:
        storage_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Invalid ZIP archive: {exc}") from exc
    repository = _store_repository(
        session, project_id, file.filename, str(storage_path), analyzed
    )
    return _code_read(repository, analyzed)


@router.post(
    "/code/github",
    response_model=CodeRepositoryRead,
    status_code=status.HTTP_201_CREATED,
)
def import_code_from_github(
    project_id: int,
    payload: GitHubRepositoryImport,
    session: Session = Depends(get_session),
) -> CodeRepositoryRead:
    get_project_or_404(project_id, session)
    try:
        storage_path, filename = import_github_archive(project_id, payload.url)
        analyzed = analyze_code_archive(storage_path)
    except (GitHubImportError, zipfile.BadZipFile, InvalidCodeArchiveError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    repository = _store_repository(session, project_id, filename, str(storage_path), analyzed)
    return _code_read(repository, analyzed)


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


@router.get("/code/analysis", response_model=CodeAnalysisRead)
def read_latest_code_analysis(
    project_id: int,
    session: Session = Depends(get_session),
) -> CodeAnalysisRead:
    get_project_or_404(project_id, session)
    analysis = workspace_service.get_code_analysis(session, project_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="Code archive has not been uploaded")
    return CodeAnalysisRead(**analysis)


def _raise_file_access_error(exc: FileAccessError) -> None:
    if isinstance(exc, RepositoryFileNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, FileTooLargeError):
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    if isinstance(exc, FileNotEditableError):
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    if isinstance(exc, InvalidRepositoryPathError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/workspace/code-tree", response_model=list[WorkspaceCodeTreeNode])
def read_code_tree(
    project_id: str,
    session: Session = Depends(get_session),
) -> list[WorkspaceCodeTreeNode]:
    numeric_id = parse_workspace_project_id(project_id)
    if numeric_id is None:
        payload = workspace_payload(project_id)
        return [WorkspaceCodeTreeNode(**item) for item in payload["code_tree"]]

    get_project_or_404(numeric_id, session)
    tree = workspace_service.get_code_tree(session, numeric_id)
    if not tree:
        raise HTTPException(status_code=404, detail="Code archive has not been uploaded")
    return [WorkspaceCodeTreeNode(**item) for item in tree]


@router.get("/workspace/code-files/{file_path:path}", response_model=WorkspaceCodeFileRead)
def read_code_file(
    project_id: str,
    file_path: str,
    session: Session = Depends(get_session),
) -> WorkspaceCodeFileRead:
    numeric_id = parse_workspace_project_id(project_id)
    if numeric_id is None:
        payload = code_file_payload(project_id, file_path)
        if payload is None:
            raise HTTPException(status_code=404, detail="Code file not found in prototype")
        return WorkspaceCodeFileRead(**payload)

    get_project_or_404(numeric_id, session)
    if not is_editor_readable_file(file_path):
        raise HTTPException(status_code=415, detail="该文件类型不支持在编辑器中打开。")
    try:
        payload = workspace_service.get_code_file(session, numeric_id, file_path)
    except FileAccessError as exc:
        _raise_file_access_error(exc)
    if payload is None:
        raise HTTPException(status_code=404, detail="Code file not found")
    return WorkspaceCodeFileRead(**payload)


@router.put("/workspace/code-files/{file_path:path}", response_model=WorkspaceCodeFileSaveResult)
def save_code_file(
    project_id: str,
    file_path: str,
    payload: WorkspaceCodeFileUpdate,
    session: Session = Depends(get_session),
) -> WorkspaceCodeFileSaveResult:
    numeric_id = parse_workspace_project_id(project_id)
    if numeric_id is None:
        if code_file_payload(project_id, file_path) is None:
            raise HTTPException(status_code=404, detail="Code file not found in prototype")
        return WorkspaceCodeFileSaveResult(
            project_id=project_id,
            path=file_path,
            status="accepted",
            message=f"Prototype save accepted with {len(payload.content)} characters.",
        )

    get_project_or_404(numeric_id, session)
    if not is_editor_readable_file(file_path):
        raise HTTPException(status_code=415, detail="该文件类型不支持在编辑器中打开。")
    try:
        result = workspace_service.save_code_file(session, numeric_id, file_path, payload.content)
    except FileAccessError as exc:
        _raise_file_access_error(exc)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return WorkspaceCodeFileSaveResult(**result)


@router.get("/workspace/tensor-flow", response_model=WorkspaceTensorFlowRead)
def read_tensor_flow(
    project_id: str,
    session: Session = Depends(get_session),
) -> WorkspaceTensorFlowRead:
    numeric_id = parse_workspace_project_id(project_id)
    if numeric_id is None:
        return WorkspaceTensorFlowRead(**tensor_flow_payload(project_id))
    get_project_or_404(numeric_id, session)
    return WorkspaceTensorFlowRead(**workspace_service.get_tensor_flow(session, numeric_id))
