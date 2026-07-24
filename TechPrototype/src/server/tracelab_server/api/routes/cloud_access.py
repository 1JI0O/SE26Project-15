from fastapi import HTTPException
from sqlmodel import Session, select

from tracelab_server.auth.dependencies import CurrentIdentity
from tracelab_server.core.config import settings
from tracelab_server.models.cloud_entities import WorkspaceMember

ROLE_LEVEL = {"viewer": 1, "editor": 2, "owner": 3}


def require_cloud_sync_feature() -> None:
    if not settings.cloud_sync_feature_enabled:
        raise HTTPException(status_code=503, detail="Cloud sync is not enabled")


def require_workspace_access(
    session: Session,
    identity: CurrentIdentity,
    workspace_id: str,
    minimum_role: str = "viewer",
) -> WorkspaceMember:
    membership = session.exec(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == identity.user_id,
        )
    ).first()
    if membership is None or ROLE_LEVEL.get(membership.role, 0) < ROLE_LEVEL[minimum_role]:
        raise HTTPException(status_code=403, detail="Workspace access denied")
    return membership
