from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlmodel import SQLModel, create_engine

from app.db.migration_runner import _drop_drifted_target_tables, upgrade_database


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
    assert revision == "0012_trace_link_repair"
    assert project == ("preserved", "legacy data", "local_only")
    tables = set(inspect(engine).get_table_names())
    assert {
        "local_sync_outbox",
        "local_artifact_version",
        "agent_analysis_job",
        "agent_analysis_artifact",
        "paper_target",
        "code_target",
        "trace_review_event",
    } <= tables
    assert "user_account" not in tables


def test_0012_repairs_early_0010_trace_target_drift(tmp_path: Path) -> None:
    """Regression: early 0010 builds created an incompatible trace-target schema.

    A DB stamped 0011 whose ``trace_link`` lacks the agent columns and whose
    ``paper_target``/``code_target``/``trace_review_event`` use the old prototype schema
    must be repaired by 0012 so Agent trace persistence stops raising
    ``no such column: trace_link.artifact_id`` / ``paper_target.target_id``.
    """

    database = tmp_path / "drifted.db"
    engine = create_engine(f"sqlite:///{database}")
    config = Config()
    config.set_main_option(
        "script_location",
        str(Path(__file__).resolve().parents[1] / "app" / "db" / "migrations"),
    )
    config.set_main_option("sqlalchemy.url", str(engine.url))
    # Reach the pre-0010 schema, then hand-build the old-prototype trace-target tables
    # and stamp forward to 0011 without ever running the real 0010 column adds.
    command.upgrade(config, "0009_agent_analysis")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE paper_target (id INTEGER PRIMARY KEY, public_id VARCHAR(36), "
                "project_id INTEGER, is_interactive BOOLEAN, created_at DATETIME)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE code_target (id INTEGER PRIMARY KEY, public_id VARCHAR(36), "
                "project_id INTEGER, is_interactive BOOLEAN, created_at DATETIME)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE trace_review_event (id INTEGER PRIMARY KEY, public_id VARCHAR(36), "
                "project_id INTEGER, event_type VARCHAR(32), created_at DATETIME)"
            )
        )
        # Old 0010 only added these three trace_link columns.
        for column in ("paper_target_id VARCHAR(72)", "code_target_id VARCHAR(72)"):
            connection.execute(text(f"ALTER TABLE trace_link ADD COLUMN {column}"))
        connection.execute(
            text("ALTER TABLE trace_link ADD COLUMN relevance FLOAT NOT NULL DEFAULT 0")
        )
        connection.execute(
            text(
                "ALTER TABLE integration_config ADD COLUMN "
                "agent_analysis_model VARCHAR(160) NOT NULL DEFAULT ''"
            )
        )
        connection.execute(
            text("UPDATE alembic_version SET version_num='0011_agent_analysis_model'")
        )

    upgrade_database(engine, SQLModel.metadata)

    inspector = inspect(engine)
    trace_link_columns = {column["name"] for column in inspector.get_columns("trace_link")}
    assert {
        "artifact_id",
        "score_basis_json",
        "provenance_json",
        "supersedes_trace_id",
    } <= trace_link_columns
    paper_target_columns = {column["name"] for column in inspector.get_columns("paper_target")}
    assert "target_id" in paper_target_columns
    assert "is_interactive" not in paper_target_columns
    code_target_columns = {column["name"] for column in inspector.get_columns("code_target")}
    assert {"target_id", "role", "artifact_id"} <= code_target_columns
    review_columns = {column["name"] for column in inspector.get_columns("trace_review_event")}
    assert {"event_id", "action", "actor_type"} <= review_columns
    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert revision == "0012_trace_link_repair"


def test_drop_drifted_target_tables_only_drops_prototype_schema(tmp_path: Path) -> None:
    """The no-alembic fallback drops only prototype-schema target tables, not valid ones."""

    engine = create_engine(f"sqlite:///{tmp_path / 'targets.db'}")
    with engine.begin() as connection:
        # Prototype (drifted) paper_target: integer id PK, no target_id.
        connection.execute(
            text("CREATE TABLE paper_target (id INTEGER PRIMARY KEY, is_interactive BOOLEAN)")
        )
        # Canonical code_target: has target_id, must be preserved.
        connection.execute(
            text("CREATE TABLE code_target (target_id VARCHAR(72) PRIMARY KEY, role VARCHAR(64))")
        )

    _drop_drifted_target_tables(engine)

    tables = set(inspect(engine).get_table_names())
    assert "paper_target" not in tables  # drifted → dropped
    assert "code_target" in tables  # canonical → kept
