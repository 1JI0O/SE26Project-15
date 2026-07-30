import importlib
from pathlib import Path
from types import ModuleType

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlmodel import create_engine

MIGRATION = importlib.import_module(
    "app.db.migrations.versions.0014_project_deep_thinking"
)


def _config(database: Path) -> Config:
    config = Config()
    config.set_main_option(
        "script_location",
        str(Path(__file__).resolve().parents[1] / "app" / "db" / "migrations"),
    )
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    return config


def test_0014_adds_a_false_default_without_losing_projects_and_downgrades(
    tmp_path: Path,
) -> None:
    database = tmp_path / "confidence-migration.db"
    config = _config(database)
    command.upgrade(config, "0004_agent_runtime")
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO project (name, description, created_at, updated_at) "
                "VALUES ('preserved', 'legacy data', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
    command.upgrade(config, "0013_rag_index")
    command.upgrade(config, "0014_project_deep_thinking")

    columns = {column["name"] for column in inspect(engine).get_columns("project")}
    with engine.connect() as connection:
        project = connection.execute(
            text("SELECT name, agent_deep_thinking FROM project")
        ).one()
    assert "agent_deep_thinking" in columns
    assert project == ("preserved", 0)

    command.downgrade(config, "0013_rag_index")
    columns = {column["name"] for column in inspect(engine).get_columns("project")}
    assert "agent_deep_thinking" not in columns


def test_0014_column_guard_handles_missing_table(monkeypatch, tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    migration = MIGRATION
    assert isinstance(migration, ModuleType)
    monkeypatch.setattr(migration.op, "get_bind", lambda: engine)
    assert migration._has_column("project", "agent_deep_thinking") is False
