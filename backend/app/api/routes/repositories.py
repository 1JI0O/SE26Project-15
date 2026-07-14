from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlmodel import Session, select

from app.api.routes.helpers import parse_workspace_project_id
from app.api.routes.projects import get_project_or_404
from app.db.session import get_session
from app.models.entities import CodeRepository
from app.schemas.repositories import (
    CodeRepositoryRead,
    WorkspaceCodeFileRead,
    WorkspaceCodeFileSaveResult,
    WorkspaceCodeFileUpdate,
    WorkspaceCodeTreeNode,
    WorkspaceTensorFlowRead,
)
from app.services import workspace_service
from app.services.code_analyzer import analyze_code_archive, is_editor_readable_file
from app.services.workspace_placeholder import (
    code_file_payload,
    tensor_flow_payload,
    workspace_payload,
)
from app.storage.file_store import save_upload

router = APIRouter(prefix="/projects/{project_id}", tags=["repositories"])


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
    payload = workspace_service.get_code_file(session, numeric_id, file_path)
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
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return WorkspaceCodeFileSaveResult(**result)


@router.get("/workspace/tensor-flow", response_model=WorkspaceTensorFlowRead)
def read_tensor_flow(project_id: str) -> WorkspaceTensorFlowRead:
    return WorkspaceTensorFlowRead(**tensor_flow_payload(project_id))
