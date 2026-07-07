from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from app.core.config import settings
from app.models.entities import CodeRepository, PaperDocument, Project, TraceLink

_ = (Project, PaperDocument, CodeRepository, TraceLink)


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
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    with Session(engine) as session:
        yield session

