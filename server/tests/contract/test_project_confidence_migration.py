from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlmodel import create_engine


def _config(database: Path) -> Config:
    config = Config()
    config.set_main_option(
        "script_location",
        str(
            Path(__file__).resolve().parents[2]
            / "tracelab_server"
            / "db"
            / "migrations"
        ),
    )
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    return config


def test_cloud_project_confidence_mode_migrates_existing_rows(tmp_path: Path) -> None:
    database = tmp_path / "cloud-confidence.db"
    config = _config(database)
    command.upgrade(config, "0001_server_baseline")
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO user_account "
                "(user_id, email_normalized, password_hash, display_name, status, "
                "is_platform_admin, created_at, updated_at) VALUES "
                "('22222222-2222-2222-2222-222222222222', 'u@example.com', 'hash', "
                "'user', 'active', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO workspace "
                "(workspace_id, name, created_by, plan, storage_limit_bytes, workspace_seq, "
                "created_at, updated_at) VALUES "
                "('11111111-1111-1111-1111-111111111111', 'w', "
                "'22222222-2222-2222-2222-222222222222', 'free', 1, 0, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO cloud_project "
                "(public_id, workspace_id, name, description, created_by, updated_by, "
                "version, sync_mode, agent_history_sync, created_at, updated_at) VALUES "
                "('33333333-3333-3333-3333-333333333333', "
                "'11111111-1111-1111-1111-111111111111', 'legacy', '', "
                "'22222222-2222-2222-2222-222222222222', "
                "'22222222-2222-2222-2222-222222222222', 1, 'cloud_enabled', 1, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )

    command.upgrade(config, "0002_project_deep_thinking")
    columns = {column["name"] for column in inspect(engine).get_columns("cloud_project")}
    with engine.connect() as connection:
        value = connection.execute(
            text(
                "SELECT agent_deep_thinking FROM cloud_project "
                "WHERE name = 'legacy'"
            )
        ).scalar_one()
    assert "agent_deep_thinking" in columns
    assert value == 0
