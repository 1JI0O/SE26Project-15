from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from app.core.config import settings
from app.db.migration_runner import upgrade_database
from app.models.entities import (
    AgentAnalysisArtifact,
    AgentAnalysisJob,
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
from app.models.sync import (
    LocalSyncConflict,
    LocalSyncInbox,
    LocalSyncOutbox,
    LocalSyncState,
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
    AgentAnalysisJob,
    AgentAnalysisArtifact,
    RepositoryAnalysisJob,
    IntegrationConfig,
    LocalArtifactVersion,
    LocalSyncOutbox,
    LocalSyncState,
    LocalSyncConflict,
    LocalSyncInbox,
)


def _connect_args() -> dict:
    if settings.database_url.startswith("sqlite"):
        # Agent analysis workers share this SQLite file; a busy timeout +
        # check_same_thread=False are required to avoid OperationalError under
        # concurrent tool writes and progress updates.
        return {"check_same_thread": False, "timeout": 30}
    return {}


def _ensure_sqlite_parent() -> None:
    if not settings.database_url.startswith("sqlite:///"):
        return
    db_path = settings.database_url.removeprefix("sqlite:///")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)


def _configure_sqlite(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


_ensure_sqlite_parent()
engine = create_engine(settings.database_url, connect_args=_connect_args(), echo=False)
if settings.database_url.startswith("sqlite"):
    from sqlalchemy import event

    event.listen(engine, "connect", _configure_sqlite)


def init_db() -> None:
    upgrade_database(engine, SQLModel.metadata)


def get_session() -> Session:
    with Session(engine) as session:
        yield session
