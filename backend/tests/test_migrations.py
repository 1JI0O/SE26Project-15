from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlmodel import SQLModel, create_engine

from app.db.migration_runner import upgrade_database


def test_fresh_sqlite_migration_reaches_local_head_without_cloud_tables(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    upgrade_database(engine, SQLModel.metadata)
    tables = set(inspect(engine).get_table_names())
    assert {"project", "local_sync_outbox", "local_artifact_version"} <= tables
    assert {"user_account", "workspace", "sync_event", "blob_object"}.isdisjoint(tables)


def test_desktop_schema_created_at_revision_four_but_stamped_one_upgrades_losslessly(
    tmp_path: Path,
) -> None:
    """Regression for Desktop builds that used create_all with a stale stamp."""

    database = tmp_path / "legacy-desktop.db"
    engine = create_engine(f"sqlite:///{database}")
    config = Config()
    config.set_main_option(
        "script_location",
        str(Path(__file__).resolve().parents[1] / "app" / "db" / "migrations"),
    )
    config.set_main_option("sqlalchemy.url", str(engine.url))
    command.upgrade(config, "0004_agent_runtime")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO project (name, description, created_at, updated_at) "
                "VALUES ('preserved', 'legacy data', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text("UPDATE alembic_version SET version_num='0001_legacy_baseline'")
        )

    upgrade_database(engine, SQLModel.metadata)

    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        project = connection.execute(
            text("SELECT name, description, sync_mode FROM project")
        ).one()
    assert revision == "0008_local_artifact_versions"
    assert project == ("preserved", "legacy data", "local_only")
    tables = set(inspect(engine).get_table_names())
    assert {"local_sync_outbox", "local_artifact_version"} <= tables
    assert "user_account" not in tables
