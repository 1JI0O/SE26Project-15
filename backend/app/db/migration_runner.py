from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import Engine, inspect, text


def _alembic_config(database_url: str) -> Any:
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(Path(__file__).with_name("migrations")))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def _run_alembic(engine: Engine) -> None:
    from alembic import command

    config = _alembic_config(str(engine.url))
    tables = set(inspect(engine).get_table_names())
    if "project" in tables and "alembic_version" not in tables:
        command.stamp(config, "0001_legacy_baseline")
    command.upgrade(config, "head")


def _column_names(engine: Engine, table: str) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns(table)}


def _add_missing_columns(engine: Engine, table: str, definitions: dict[str, str]) -> None:
    existing = _column_names(engine, table)
    with engine.begin() as connection:
        for name, definition in definitions.items():
            if name not in existing:
                connection.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {definition}'))


def _run_sqlite_compatibility_upgrade(engine: Engine, metadata: Any) -> None:
    """Temporary bridge until the integration branch adds the Alembic dependency.

    It upgrades only the legacy SQLite schema shipped in iteration 1. Alembic remains
    the authoritative migration path and takes over automatically when installed.
    """

    tables = set(inspect(engine).get_table_names())
    if "project" not in tables:
        metadata.create_all(engine)
        return

    _add_missing_columns(
        engine,
        "paper_document",
        {
            "parser": "VARCHAR(64) NOT NULL DEFAULT 'legacy'",
            "parser_version": "VARCHAR(128) NOT NULL DEFAULT ''",
            "parse_status": "VARCHAR(32) NOT NULL DEFAULT 'succeeded'",
            "content_hash": "VARCHAR(64) NOT NULL DEFAULT ''",
            "pages_json": "JSON NOT NULL DEFAULT '[]'",
        },
    )
    _add_missing_columns(
        engine,
        "code_repository",
        {
            "tensor_graph_json": "JSON NOT NULL DEFAULT '{\"nodes\":[],\"edges\":[]}'",
            "revision": "INTEGER NOT NULL DEFAULT 1",
            "updated_at": "DATETIME",
        },
    )
    _add_missing_columns(
        engine,
        "trace_link",
        {
            "trace_id": "VARCHAR(64)",
            "paper_document_id": "INTEGER",
            "code_repository_id": "INTEGER",
            "code_revision": "INTEGER NOT NULL DEFAULT 1",
            "static_confidence": "FLOAT NOT NULL DEFAULT 0",
            "llm_confidence": "FLOAT",
            "source": "VARCHAR(32) NOT NULL DEFAULT 'legacy'",
            "evidence_json": "JSON NOT NULL DEFAULT '[]'",
            "uncertainty_json": "JSON NOT NULL DEFAULT '{\"level\":\"high\",\"reasons\":[]}'",
            "model_info_json": "JSON",
            "fingerprint": "VARCHAR(64)",
            "status": "VARCHAR(32) NOT NULL DEFAULT 'stale'",
            "stale_reason": "VARCHAR(128) DEFAULT 'legacy_missing_version_evidence'",
            "decided_at": "DATETIME",
            "updated_at": "DATETIME",
        },
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE code_repository SET updated_at = created_at "
                "WHERE updated_at IS NULL"
            )
        )
        connection.execute(
            text(
                "UPDATE trace_link SET "
                "trace_id = 'trace-legacy-' || id, "
                "fingerprint = 'legacy-' || id, "
                "source = 'legacy', status = 'stale', "
                "stale_reason = 'legacy_missing_version_evidence', "
                "static_confidence = confidence, updated_at = created_at "
                "WHERE trace_id IS NULL OR fingerprint IS NULL"
            )
        )
        connection.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS uq_trace_link_trace_id ON trace_link(trace_id)")
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_trace_link_fingerprint "
                "ON trace_link(fingerprint)"
            )
        )
    metadata.create_all(engine)


def upgrade_database(engine: Engine, metadata: Any) -> None:
    try:
        import alembic  # noqa: F401
    except ModuleNotFoundError:
        if engine.url.get_backend_name() != "sqlite":
            raise RuntimeError("Alembic is required for non-SQLite databases") from None
        _run_sqlite_compatibility_upgrade(engine, metadata)
        return
    _run_alembic(engine)
