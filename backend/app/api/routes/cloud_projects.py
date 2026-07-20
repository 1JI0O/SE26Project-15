from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.api.routes.cloud_access import require_cloud_sync_feature, require_workspace_access
from app.auth.dependencies import CurrentIdentity, require_verified
from app.db.session import get_session
from app.models.cloud_entities import CloudProject, DeviceProjectBinding, WorkspaceMember
from app.schemas.cloud import (
    CloudProjectCreate,
    CloudProjectPatch,
    CloudProjectRead,
    DeviceProjectSyncPatch,
    DeviceProjectSyncRead,
    SyncOperation,
)
from app.services.cloud_sync import apply_operation

router = APIRouter(
    prefix="/projects",
    tags=["cloud-projects"],
    dependencies=[Depends(require_cloud_sync_feature)],
)


def _read(item: CloudProject) -> CloudProjectRead:
    return CloudProjectRead(
        public_id=item.public_id,
        workspace_id=item.workspace_id,
        name=item.name,
        description=item.description,
        version=item.version,
        sync_mode=item.sync_mode,
        agent_history_sync=item.agent_history_sync,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.get("", response_model=list[CloudProjectRead])
def list_projects(
    workspace_id: str | None = None,
    identity: CurrentIdentity = Depends(require_verified),
    session: Session = Depends(get_session),
) -> list[CloudProjectRead]:
    workspace_ids = [
        row.workspace_id
        for row in session.exec(
            select(WorkspaceMember).where(WorkspaceMember.user_id == identity.user_id)
        ).all()
    ]
    if workspace_id:
        require_workspace_access(session, identity, workspace_id)
        workspace_ids = [workspace_id]
    if not workspace_ids:
        return []
    rows = session.exec(
        select(CloudProject)
        .where(CloudProject.workspace_id.in_(workspace_ids), CloudProject.deleted_at.is_(None))
        .order_by(CloudProject.updated_at.desc())
    ).all()
    return [_read(item) for item in rows]


@router.post("", response_model=CloudProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: CloudProjectCreate,
    identity: CurrentIdentity = Depends(require_verified),
    session: Session = Depends(get_session),
) -> CloudProjectRead:
    require_workspace_access(session, identity, payload.workspace_id, "editor")
    public_id = payload.public_id or str(uuid4())
    result = apply_operation(
        session,
        identity,
        SyncOperation(
            workspace_id=payload.workspace_id,
            device_id=identity.device_id,
            client_operation_id=str(uuid4()),
            entity_type="project",
            entity_public_id=public_id,
            operation="upsert",
            base_version=0,
            payload={
                "name": payload.name,
                "description": payload.description,
                "agent_history_sync": payload.agent_history_sync,
            },
        ),
        require_project_binding=False,
    )
    if result.status != "applied":
        raise HTTPException(status_code=409, detail="Project already exists")
    return _read(session.get(CloudProject, public_id))


@router.get("/{project_id}", response_model=CloudProjectRead)
def read_project(
    project_id: str,
    identity: CurrentIdentity = Depends(require_verified),
    session: Session = Depends(get_session),
) -> CloudProjectRead:
    item = session.get(CloudProject, project_id)
    if item is None or item.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Project not found")
    require_workspace_access(session, identity, item.workspace_id)
    return _read(item)


@router.get("/{project_id}/device-sync", response_model=DeviceProjectSyncRead)
def read_device_sync(
    project_id: str,
    identity: CurrentIdentity = Depends(require_verified),
    session: Session = Depends(get_session),
) -> DeviceProjectSyncRead:
    item = session.get(CloudProject, project_id)
    if item is None or item.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Project not found")
    require_workspace_access(session, identity, item.workspace_id)
    binding = session.exec(
        select(DeviceProjectBinding).where(
            DeviceProjectBinding.device_id == identity.device_id,
            DeviceProjectBinding.project_public_id == project_id,
        )
    ).first()
    return DeviceProjectSyncRead(
        project_public_id=project_id,
        device_id=identity.device_id,
        sync_mode=binding.sync_mode if binding else "cloud_detached",
    )


@router.patch("/{project_id}/device-sync", response_model=DeviceProjectSyncRead)
def patch_device_sync(
    project_id: str,
    payload: DeviceProjectSyncPatch,
    identity: CurrentIdentity = Depends(require_verified),
    session: Session = Depends(get_session),
) -> DeviceProjectSyncRead:
    item = session.get(CloudProject, project_id)
    if item is None or item.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Project not found")
    require_workspace_access(session, identity, item.workspace_id, "viewer")
    binding = session.exec(
        select(DeviceProjectBinding).where(
            DeviceProjectBinding.device_id == identity.device_id,
            DeviceProjectBinding.project_public_id == project_id,
        )
    ).first()
    if binding is None:
        binding = DeviceProjectBinding(
            device_id=identity.device_id,
            workspace_id=item.workspace_id,
            project_public_id=project_id,
        )
    binding.sync_mode = payload.sync_mode
    session.add(binding)
    session.commit()
    return DeviceProjectSyncRead(
        project_public_id=project_id,
        device_id=identity.device_id,
        sync_mode=payload.sync_mode,
    )


@router.patch("/{project_id}", response_model=CloudProjectRead)
def patch_project(
    project_id: str,
    payload: CloudProjectPatch,
    identity: CurrentIdentity = Depends(require_verified),
    session: Session = Depends(get_session),
) -> CloudProjectRead:
    item = session.get(CloudProject, project_id)
    if item is None or item.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Project not found")
    result = apply_operation(
        session,
        identity,
        SyncOperation(
            workspace_id=item.workspace_id,
            device_id=identity.device_id,
            client_operation_id=str(uuid4()),
            entity_type="project",
            entity_public_id=project_id,
            operation="upsert",
            base_version=payload.base_version,
            payload=payload.model_dump(exclude_none=True, exclude={"base_version"}),
        ),
        require_project_binding=False,
    )
    if result.status == "conflict":
        raise HTTPException(
            status_code=409, detail={"code": "version_conflict", "remote": result.remote}
        )
    return _read(session.get(CloudProject, project_id))


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: str,
    base_version: int,
    identity: CurrentIdentity = Depends(require_verified),
    session: Session = Depends(get_session),
) -> None:
    item = session.get(CloudProject, project_id)
    if item is None or item.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Project not found")
    require_workspace_access(session, identity, item.workspace_id, "owner")
    result = apply_operation(
        session,
        identity,
        SyncOperation(
            workspace_id=item.workspace_id,
            device_id=identity.device_id,
            client_operation_id=str(uuid4()),
            entity_type="project",
            entity_public_id=project_id,
            operation="delete",
            base_version=base_version,
            payload={},
        ),
        require_project_binding=False,
    )
    if result.status == "conflict":
        raise HTTPException(
            status_code=409, detail={"code": "version_conflict", "remote": result.remote}
        )
