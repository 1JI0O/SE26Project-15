from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session, select

from tracelab_server.api.routes.cloud_access import (
    require_cloud_sync_feature,
    require_workspace_access,
)
from tracelab_server.auth.dependencies import CurrentIdentity, require_verified
from tracelab_server.db.session import get_session
from tracelab_server.models.cloud_entities import ArtifactVersion, CloudEntity, CloudProject
from tracelab_server.schemas.cloud import CloudEntityCommand, SyncEntityType, UuidStr
from tracelab_server.services.cloud_domain import execute_cloud_entity_command

router = APIRouter(
    prefix="/projects/{project_id}",
    tags=["cloud-domain"],
    dependencies=[Depends(require_cloud_sync_feature)],
)


def _project(session: Session, identity: CurrentIdentity, project_id: str) -> CloudProject:
    project = session.get(CloudProject, project_id)
    if project is None or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Project not found")
    require_workspace_access(session, identity, project.workspace_id, "viewer")
    return project


def _read(entity: CloudEntity) -> dict:
    return {
        "public_id": entity.public_id,
        "project_public_id": entity.project_public_id,
        "entity_type": entity.entity_type,
        "version": entity.version,
        "payload": entity.payload_json,
        "deleted_at": entity.deleted_at,
        "updated_at": entity.updated_at,
    }


@router.get("/entities")
def list_entities(
    project_id: UuidStr,
    entity_type: SyncEntityType | None = Query(default=None),
    identity: CurrentIdentity = Depends(require_verified),
    session: Session = Depends(get_session),
) -> list[dict]:
    project = _project(session, identity, project_id)
    statement = select(CloudEntity).where(
        CloudEntity.workspace_id == project.workspace_id,
        CloudEntity.project_public_id == project_id,
        CloudEntity.deleted_at.is_(None),
    )
    if entity_type is not None:
        statement = statement.where(CloudEntity.entity_type == entity_type)
    return [_read(row) for row in session.exec(statement.order_by(CloudEntity.updated_at.desc()))]


@router.post("/entities/{entity_type}", status_code=status.HTTP_201_CREATED)
def create_entity(
    project_id: UuidStr,
    entity_type: SyncEntityType,
    command: CloudEntityCommand,
    identity: CurrentIdentity = Depends(require_verified),
    session: Session = Depends(get_session),
) -> dict:
    project = _project(session, identity, project_id)
    require_workspace_access(session, identity, project.workspace_id, "editor")
    result = execute_cloud_entity_command(
        session,
        identity,
        project,
        entity_type,
        command.public_id or str(uuid4()),
        "upsert",
        command.base_version,
        command.payload,
    )
    if result.status == "conflict":
        raise HTTPException(status_code=409, detail=result.remote)
    return result.remote or {}


@router.patch("/entities/{entity_type}/{entity_id}")
def update_entity(
    project_id: UuidStr,
    entity_type: SyncEntityType,
    entity_id: UuidStr,
    command: CloudEntityCommand,
    identity: CurrentIdentity = Depends(require_verified),
    session: Session = Depends(get_session),
) -> dict:
    project = _project(session, identity, project_id)
    require_workspace_access(session, identity, project.workspace_id, "editor")
    result = execute_cloud_entity_command(
        session,
        identity,
        project,
        entity_type,
        entity_id,
        "upsert",
        command.base_version,
        command.payload,
    )
    if result.status == "conflict":
        raise HTTPException(status_code=409, detail=result.remote)
    return result.remote or {}


@router.delete("/entities/{entity_type}/{entity_id}", status_code=204)
def delete_entity(
    project_id: UuidStr,
    entity_type: SyncEntityType,
    entity_id: UuidStr,
    base_version: int = Query(ge=1),
    identity: CurrentIdentity = Depends(require_verified),
    session: Session = Depends(get_session),
) -> None:
    project = _project(session, identity, project_id)
    require_workspace_access(session, identity, project.workspace_id, "editor")
    result = execute_cloud_entity_command(
        session, identity, project, entity_type, entity_id, "delete", base_version, {}
    )
    if result.status == "conflict":
        raise HTTPException(status_code=409, detail=result.remote)


@router.get("/artifacts/{entity_type}/{entity_id}/versions")
def list_artifact_versions(
    project_id: UuidStr,
    entity_type: SyncEntityType,
    entity_id: UuidStr,
    identity: CurrentIdentity = Depends(require_verified),
    session: Session = Depends(get_session),
) -> list[ArtifactVersion]:
    project = _project(session, identity, project_id)
    return list(
        session.exec(
            select(ArtifactVersion)
            .where(
                ArtifactVersion.workspace_id == project.workspace_id,
                ArtifactVersion.project_public_id == project_id,
                ArtifactVersion.entity_type == entity_type,
                ArtifactVersion.entity_public_id == entity_id,
                ArtifactVersion.deleted_at.is_(None),
            )
            .order_by(ArtifactVersion.version_number.desc())
        ).all()
    )


@router.post("/artifacts/{entity_type}/{entity_id}/versions/{version_id}/select")
def select_artifact_version(
    project_id: UuidStr,
    entity_type: SyncEntityType,
    entity_id: UuidStr,
    version_id: UuidStr,
    base_version: int = Query(ge=1),
    identity: CurrentIdentity = Depends(require_verified),
    session: Session = Depends(get_session),
) -> dict:
    project = _project(session, identity, project_id)
    require_workspace_access(session, identity, project.workspace_id, "editor")
    result = execute_cloud_entity_command(
        session,
        identity,
        project,
        entity_type,
        entity_id,
        "select_version",
        base_version,
        {"version_id": version_id},
    )
    if result.status == "conflict":
        raise HTTPException(status_code=409, detail=result.remote)
    return result.remote or {}
