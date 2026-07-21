from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.db.session import get_session
from app.models.entities import Project, utc_now
from app.schemas.projects import (
    ProjectBatchDeleteRead,
    ProjectBatchDeleteRequest,
    ProjectCreate,
    ProjectRead,
    ProjectUpdate,
)
from app.services.local_sync import project_payload, record_local_operation
from app.services.project_service import delete_projects

router = APIRouter(prefix="/projects", tags=["projects"])


def get_project_or_404(project_id: int, session: Session) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


@router.get("", response_model=list[ProjectRead])
def list_projects(session: Session = Depends(get_session)) -> list[Project]:
    statement = select(Project).order_by(Project.created_at.desc())
    return list(session.exec(statement).all())


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, session: Session = Depends(get_session)) -> Project:
    project = Project(name=payload.name, description=payload.description)
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


@router.post("/batch-delete", response_model=ProjectBatchDeleteRead)
def batch_delete_projects(
    payload: ProjectBatchDeleteRequest,
    session: Session = Depends(get_session),
) -> ProjectBatchDeleteRead:
    deleted_ids, missing_ids = delete_projects(session, payload.project_ids)
    return ProjectBatchDeleteRead(deleted_ids=deleted_ids, missing_ids=missing_ids)


@router.get("/{project_id}", response_model=ProjectRead)
def read_project(project_id: int, session: Session = Depends(get_session)) -> Project:
    return get_project_or_404(project_id, session)


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: int,
    payload: ProjectUpdate,
    session: Session = Depends(get_session),
) -> Project:
    project = get_project_or_404(project_id, session)
    changed = False
    if payload.name is not None and payload.name != project.name:
        project.name = payload.name
        changed = True
    if payload.description is not None and payload.description != project.description:
        project.description = payload.description
        changed = True
    if changed:
        project.updated_at = utc_now()
        project.version += 1
        session.add(project)
        session.flush()
        # If the project is already synced, record the rename/description change
        # so it propagates on the next push.
        record_local_operation(
            session,
            project,
            "project",
            project.public_id,
            project_payload(project),
            base_version=project.version - 1,
        )
        session.commit()
        session.refresh(project)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: int, session: Session = Depends(get_session)) -> None:
    get_project_or_404(project_id, session)
    delete_projects(session, [project_id])
