from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, func, select

from app.api.routes.cloud_access import require_workspace_access
from app.auth.dependencies import CurrentIdentity, require_verified
from app.auth.service import audit, normalize_email
from app.core.config import settings
from app.db.session import get_session
from app.models.cloud_entities import SyncEvent, UserAccount, Workspace, WorkspaceMember
from app.models.entities import utc_now
from app.schemas.cloud import (
    WorkspaceCreate,
    WorkspaceMemberCreate,
    WorkspaceMemberPatch,
    WorkspaceMemberRead,
    WorkspaceRead,
)

router = APIRouter(prefix="/workspaces", tags=["cloud-workspaces"])


def _emit_member_event(
    session: Session,
    workspace: Workspace,
    user_id: str,
    operation: str,
    role: str | None,
) -> None:
    workspace.workspace_seq += 1
    workspace.updated_at = utc_now()
    session.add(workspace)
    session.add(
        SyncEvent(
            workspace_id=workspace.workspace_id,
            workspace_seq=workspace.workspace_seq,
            entity_type="workspace_member",
            entity_public_id=user_id,
            operation=operation,
            entity_version=workspace.workspace_seq,
            payload_json={"user_id": user_id, "role": role},
        )
    )


def _workspace_read(workspace: Workspace, role: str) -> WorkspaceRead:
    return WorkspaceRead(
        workspace_id=workspace.workspace_id,
        name=workspace.name,
        role=role,
        plan=workspace.plan,
        storage_limit_bytes=workspace.storage_limit_bytes,
        workspace_seq=workspace.workspace_seq,
    )


@router.get("", response_model=list[WorkspaceRead])
def list_workspaces(
    identity: CurrentIdentity = Depends(require_verified), session: Session = Depends(get_session)
) -> list[WorkspaceRead]:
    memberships = session.exec(
        select(WorkspaceMember).where(WorkspaceMember.user_id == identity.user_id)
    ).all()
    return [
        _workspace_read(workspace, item.role)
        for item in memberships
        if (workspace := session.get(Workspace, item.workspace_id)) is not None
    ]


@router.post("", response_model=WorkspaceRead, status_code=status.HTTP_201_CREATED)
def create_workspace(
    payload: WorkspaceCreate,
    identity: CurrentIdentity = Depends(require_verified),
    session: Session = Depends(get_session),
) -> WorkspaceRead:
    workspace = Workspace(
        name=payload.name.strip(),
        created_by=identity.user_id,
        storage_limit_bytes=settings.cloud_account_quota_bytes,
    )
    session.add(workspace)
    session.flush()
    session.add(
        WorkspaceMember(workspace_id=workspace.workspace_id, user_id=identity.user_id, role="owner")
    )
    audit(
        session,
        "workspace.create",
        actor_id=identity.user_id,
        workspace_id=workspace.workspace_id,
        target=workspace.workspace_id,
    )
    session.commit()
    return _workspace_read(workspace, "owner")


@router.get("/{workspace_id}", response_model=WorkspaceRead)
def read_workspace(
    workspace_id: str,
    identity: CurrentIdentity = Depends(require_verified),
    session: Session = Depends(get_session),
) -> WorkspaceRead:
    member = require_workspace_access(session, identity, workspace_id)
    workspace = session.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return _workspace_read(workspace, member.role)


@router.get("/{workspace_id}/members", response_model=list[WorkspaceMemberRead])
def list_members(
    workspace_id: str,
    identity: CurrentIdentity = Depends(require_verified),
    session: Session = Depends(get_session),
) -> list[WorkspaceMemberRead]:
    require_workspace_access(session, identity, workspace_id, "viewer")
    members = session.exec(
        select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id)
    ).all()
    result = []
    for member in members:
        user = session.get(UserAccount, member.user_id)
        if user:
            result.append(
                WorkspaceMemberRead(
                    user_id=user.user_id,
                    email=user.email_normalized,
                    display_name=user.display_name,
                    role=member.role,
                )
            )
    return result


@router.post(
    "/{workspace_id}/members",
    response_model=WorkspaceMemberRead,
    status_code=status.HTTP_201_CREATED,
)
def add_member(
    workspace_id: str,
    payload: WorkspaceMemberCreate,
    identity: CurrentIdentity = Depends(require_verified),
    session: Session = Depends(get_session),
) -> WorkspaceMemberRead:
    require_workspace_access(session, identity, workspace_id, "owner")
    user = session.exec(
        select(UserAccount).where(UserAccount.email_normalized == normalize_email(payload.email))
    ).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    existing = session.exec(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user.user_id
        )
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="User is already a member")
    session.add(WorkspaceMember(workspace_id=workspace_id, user_id=user.user_id, role=payload.role))
    workspace = session.exec(
        select(Workspace).where(Workspace.workspace_id == workspace_id).with_for_update()
    ).one()
    _emit_member_event(session, workspace, user.user_id, "upsert", payload.role)
    audit(
        session,
        "workspace.member_add",
        actor_id=identity.user_id,
        workspace_id=workspace_id,
        target=user.user_id,
        metadata={"role": payload.role},
    )
    session.commit()
    return WorkspaceMemberRead(
        user_id=user.user_id,
        email=user.email_normalized,
        display_name=user.display_name,
        role=payload.role,
    )


@router.patch("/{workspace_id}/members/{user_id}", response_model=WorkspaceMemberRead)
def update_member(
    workspace_id: str,
    user_id: str,
    payload: WorkspaceMemberPatch,
    identity: CurrentIdentity = Depends(require_verified),
    session: Session = Depends(get_session),
) -> WorkspaceMemberRead:
    require_workspace_access(session, identity, workspace_id, "owner")
    member = session.exec(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id
        )
    ).first()
    user = session.get(UserAccount, user_id)
    if member is None or user is None:
        raise HTTPException(status_code=404, detail="Member not found")
    if member.role == "owner" and payload.role != "owner":
        owner_count = int(
            session.exec(
                select(func.count())
                .select_from(WorkspaceMember)
                .where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.role == "owner",
                )
            ).one()
        )
        if owner_count <= 1:
            raise HTTPException(status_code=409, detail="Workspace must keep an owner")
    member.role = payload.role
    session.add(member)
    workspace = session.exec(
        select(Workspace).where(Workspace.workspace_id == workspace_id).with_for_update()
    ).one()
    _emit_member_event(session, workspace, user_id, "upsert", member.role)
    audit(
        session,
        "workspace.member_role",
        actor_id=identity.user_id,
        workspace_id=workspace_id,
        target=user_id,
        metadata={"role": payload.role},
    )
    session.commit()
    return WorkspaceMemberRead(
        user_id=user.user_id,
        email=user.email_normalized,
        display_name=user.display_name,
        role=member.role,
    )


@router.delete("/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    workspace_id: str,
    user_id: str,
    identity: CurrentIdentity = Depends(require_verified),
    session: Session = Depends(get_session),
) -> None:
    require_workspace_access(session, identity, workspace_id, "owner")
    if user_id == identity.user_id:
        raise HTTPException(status_code=409, detail="Owner cannot remove self")
    member = session.exec(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id
        )
    ).first()
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")
    session.delete(member)
    workspace = session.exec(
        select(Workspace).where(Workspace.workspace_id == workspace_id).with_for_update()
    ).one()
    _emit_member_event(session, workspace, user_id, "delete", None)
    audit(
        session,
        "workspace.member_remove",
        actor_id=identity.user_id,
        workspace_id=workspace_id,
        target=user_id,
    )
    session.commit()
