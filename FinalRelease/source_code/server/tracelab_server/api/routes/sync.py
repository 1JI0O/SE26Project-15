from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from tracelab_server.api.routes.cloud_access import (
    require_cloud_sync_feature,
    require_workspace_access,
)
from tracelab_server.auth.dependencies import CurrentIdentity, require_verified
from tracelab_server.db.session import get_session
from tracelab_server.models.cloud_entities import (
    CloudEntity,
    CloudProject,
    Device,
    DeviceProjectBinding,
    EntityTombstone,
    SyncDeviceCursor,
    SyncEvent,
    Workspace,
)
from tracelab_server.models.entities import utc_now
from tracelab_server.schemas.cloud import (
    SyncAckRequest,
    SyncEventRead,
    SyncPullRead,
    SyncPushRead,
    SyncPushRequest,
    UuidStr,
)
from tracelab_server.services.cloud_sync import apply_operation

router = APIRouter(
    prefix="/sync",
    tags=["cloud-sync"],
    dependencies=[Depends(require_cloud_sync_feature)],
)


@router.get("/bootstrap")
def bootstrap(
    workspace_id: UuidStr,
    identity: CurrentIdentity = Depends(require_verified),
    session: Session = Depends(get_session),
) -> dict:
    require_workspace_access(session, identity, workspace_id, "viewer")
    workspace = session.get(Workspace, workspace_id)
    projects = session.exec(
        select(CloudProject).where(CloudProject.workspace_id == workspace_id)
    ).all()
    entities = session.exec(
        select(CloudEntity).where(CloudEntity.workspace_id == workspace_id)
    ).all()
    tombstones = session.exec(
        select(EntityTombstone).where(EntityTombstone.workspace_id == workspace_id)
    ).all()
    bindings = session.exec(
        select(DeviceProjectBinding).where(
            DeviceProjectBinding.workspace_id == workspace_id,
            DeviceProjectBinding.device_id == identity.device_id,
        )
    ).all()
    cursor = session.exec(
        select(SyncDeviceCursor).where(
            SyncDeviceCursor.workspace_id == workspace_id,
            SyncDeviceCursor.device_id == identity.device_id,
        )
    ).first()
    return {
        "workspace_id": workspace_id,
        "device_id": identity.device_id,
        "current_seq": workspace.workspace_seq if workspace else 0,
        "last_pulled_seq": cursor.last_pulled_seq if cursor else 0,
        "device_bindings": [
            {
                "project_public_id": item.project_public_id,
                "sync_mode": item.sync_mode,
            }
            for item in bindings
        ],
        "projects": [
            {
                "public_id": item.public_id,
                "name": item.name,
                "description": item.description,
                "version": item.version,
                "sync_mode": item.sync_mode,
                "agent_history_sync": item.agent_history_sync,
                "agent_deep_thinking": item.agent_deep_thinking,
                "deleted_at": item.deleted_at,
            }
            for item in projects
        ],
        "entities": [
            {
                "entity_type": item.entity_type,
                "public_id": item.public_id,
                "project_public_id": item.project_public_id,
                "version": item.version,
                "payload": item.payload_json,
                "deleted_at": item.deleted_at,
            }
            for item in entities
        ],
        "tombstones": [
            {
                "entity_type": item.entity_type,
                "entity_public_id": item.entity_public_id,
                "deleted_version": item.deleted_version,
                "expires_at": item.expires_at,
            }
            for item in tombstones
        ],
    }


@router.get("/pull", response_model=SyncPullRead)
def pull(
    workspace_id: UuidStr,
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=500),
    identity: CurrentIdentity = Depends(require_verified),
    session: Session = Depends(get_session),
) -> SyncPullRead:
    require_workspace_access(session, identity, workspace_id, "viewer")
    rows = list(
        session.exec(
            select(SyncEvent)
            .where(SyncEvent.workspace_id == workspace_id, SyncEvent.workspace_seq > after)
            .order_by(SyncEvent.workspace_seq)
            .limit(limit + 1)
        ).all()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    return SyncPullRead(
        events=[
            SyncEventRead(
                event_id=item.event_id,
                workspace_seq=item.workspace_seq,
                entity_type=item.entity_type,
                entity_public_id=item.entity_public_id,
                operation=item.operation,
                entity_version=item.entity_version,
                payload=item.payload_json,
                created_at=item.created_at,
            )
            for item in rows
        ],
        next_after=rows[-1].workspace_seq if rows else after,
        has_more=has_more,
    )


@router.post("/push", response_model=SyncPushRead)
def push(
    payload: SyncPushRequest,
    identity: CurrentIdentity = Depends(require_verified),
    session: Session = Depends(get_session),
) -> SyncPushRead:
    return SyncPushRead(
        results=[apply_operation(session, identity, operation) for operation in payload.operations]
    )


@router.post("/ack", status_code=204)
def ack(
    payload: SyncAckRequest,
    identity: CurrentIdentity = Depends(require_verified),
    session: Session = Depends(get_session),
) -> None:
    require_workspace_access(session, identity, payload.workspace_id, "viewer")
    workspace = session.get(Workspace, payload.workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if payload.last_pulled_seq > workspace.workspace_seq:
        raise HTTPException(status_code=409, detail="Cursor exceeds workspace sequence")
    device = session.get(Device, payload.device_id)
    if (
        device is None
        or device.user_id != identity.user_id
        or device.device_id != identity.device_id
    ):
        raise HTTPException(status_code=403, detail="Invalid sync device")
    cursor = session.exec(
        select(SyncDeviceCursor).where(
            SyncDeviceCursor.device_id == payload.device_id,
            SyncDeviceCursor.workspace_id == payload.workspace_id,
        )
    ).first()
    if cursor is None:
        cursor = SyncDeviceCursor(
            device_id=payload.device_id,
            workspace_id=payload.workspace_id,
            last_pulled_seq=payload.last_pulled_seq,
        )
    else:
        cursor.last_pulled_seq = max(cursor.last_pulled_seq, payload.last_pulled_seq)
        cursor.updated_at = utc_now()
    session.add(cursor)
    session.commit()
