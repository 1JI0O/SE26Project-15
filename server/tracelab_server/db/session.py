from collections.abc import Iterator
from pathlib import Path

from sqlmodel import Session, create_engine

from tracelab_server.core.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, echo=False)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


def migrate_database(database_url: str | None = None) -> None:
    from alembic import command
    from alembic.config import Config

    server_root = Path(__file__).resolve().parents[2]
    config = Config(str(server_root / "alembic.ini"))
    config.set_main_option("script_location", str(server_root / "tracelab_server/db/migrations"))
    rendered_url = database_url or engine.url.render_as_string(hide_password=False)
    config.set_main_option("sqlalchemy.url", rendered_url.replace("%", "%%"))
    command.upgrade(config, "head")


def init_db() -> None:
    """Compatibility alias for the one-shot migrator CLI."""
    migrate_database()
