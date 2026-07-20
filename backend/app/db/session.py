from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from app.core.config import settings
from app.db.migration_runner import upgrade_cloud_database, upgrade_database
from app.models.cloud_entities import (
    ArtifactVersion,
    AuditLog,
    AuthRateLimit,
    AuthSession,
    BackgroundJob,
    BlobContent,
    BlobObject,
    BlobReference,
    CloudEntity,
    CloudProject,
    Device,
    DeviceProjectBinding,
    EmailToken,
    EntityTombstone,
    LocalSyncConflict,
    LocalSyncInbox,
    LocalSyncOutbox,
    LocalSyncState,
    SyncDeviceCursor,
    SyncEvent,
    SyncReceipt,
    UploadSession,
    UserAccount,
    Workspace,
    WorkspaceMember,
)
from app.models.entities import (
    AgentCapabilitySetting,
    AgentConversation,
    AgentMemory,
    AgentMessage,
    AgentRun,
    AgentRunEvent,
    AgentToolRequest,
    CodeRepository,
    IntegrationConfig,
    LocalArtifactVersion,
    PaperDocument,
    Project,
    RepositoryAnalysisJob,
    TraceLink,
)

_ = (
    Project,
    PaperDocument,
    CodeRepository,
    TraceLink,
    AgentConversation,
    AgentMessage,
    AgentRun,
    AgentRunEvent,
    AgentMemory,
    AgentCapabilitySetting,
    AgentToolRequest,
    RepositoryAnalysisJob,
    IntegrationConfig,
    LocalArtifactVersion,
    UserAccount,
    AuthSession,
    Device,
    Workspace,
    WorkspaceMember,
    EmailToken,
    AuditLog,
    AuthRateLimit,
    CloudProject,
    CloudEntity,
    SyncEvent,
    SyncReceipt,
    SyncDeviceCursor,
    EntityTombstone,
    BlobObject,
    BlobContent,
    BlobReference,
    ArtifactVersion,
    UploadSession,
    DeviceProjectBinding,
    BackgroundJob,
    LocalSyncOutbox,
    LocalSyncState,
    LocalSyncConflict,
    LocalSyncInbox,
)


def _connect_args() -> dict[str, bool]:
    if settings.database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def _ensure_sqlite_parent() -> None:
    if not settings.database_url.startswith("sqlite:///"):
        return
    db_path = settings.database_url.removeprefix("sqlite:///")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_parent()
engine = create_engine(settings.database_url, connect_args=_connect_args(), echo=False)


def init_db() -> None:
    if settings.runtime_mode in {"cloud", "worker"}:
        upgrade_cloud_database(engine)
    else:
        upgrade_database(engine, SQLModel.metadata)


def get_session() -> Session:
    with Session(engine) as session:
        yield session
