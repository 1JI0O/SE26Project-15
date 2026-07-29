from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import Engine, inspect, text


def _database_url(engine: Engine) -> str:
    # str(engine.url) redacts the password as "***", which breaks PostgreSQL auth.
    return engine.url.render_as_string(hide_password=False)


LOCAL_REVISIONS = (
    "0001_legacy_baseline",
    "0002_trace_agent",
    "0003_integration_config",
    "0004_agent_runtime",
    "0005_runtime_events_analysis_cache",
    "0006_cloud_accounts_sync",
    "0007_cloud_consistency",
    "0008_local_artifact_versions",
    "0009_agent_analysis",
    "0010_trace_targets",
    "0011_agent_analysis_model",
    "0012_trace_link_repair",
    "0013_rag_index",
)


def _has_columns(inspector: Any, table: str, required: set[str]) -> bool:
    if not inspector.has_table(table):
        return False
    return required.issubset({column["name"] for column in inspector.get_columns(table)})


def _detect_local_revision(engine: Engine, tables: set[str]) -> str:
    """Identify schemas created by pre-Alembic/early Desktop builds.

    Several released development builds created current ORM tables with
    ``create_all`` but stamped only the iteration-1 baseline. Detection must be
    progressive: never skip a migration unless every preceding capability is
    already present.
    """

    inspector = inspect(engine)
    detected = LOCAL_REVISIONS[0]
    has_0002 = (
        _has_columns(
            inspector,
            "paper_document",
            {"parser", "parser_version", "parse_status", "content_hash", "pages_json"},
        )
        and _has_columns(
            inspector,
            "code_repository",
            {"tensor_graph_json", "revision", "updated_at"},
        )
        and _has_columns(
            inspector,
            "trace_link",
            {"trace_id", "fingerprint", "status", "evidence_json", "updated_at"},
        )
        and "agent_tool_request" in tables
    )
    if not has_0002:
        return detected
    detected = LOCAL_REVISIONS[1]
    if "integration_config" not in tables:
        return detected
    detected = LOCAL_REVISIONS[2]
    has_0004 = {
        "agent_conversation",
        "agent_message",
        "agent_run",
        "agent_memory",
    }.issubset(tables) and _has_columns(
        inspector, "agent_tool_request", {"conversation_id", "run_id"}
    )
    if not has_0004:
        return detected
    detected = LOCAL_REVISIONS[3]
    has_0005 = {
        "agent_run_event",
        "agent_capability_setting",
        "repository_analysis_job",
    }.issubset(tables) and _has_columns(
        inspector, "agent_run", {"capability_snapshot_json"}
    )
    if not has_0005:
        return detected
    detected = LOCAL_REVISIONS[4]
    has_0006 = (
        _has_columns(
            inspector,
            "project",
            {"public_id", "cloud_workspace_id", "version", "sync_mode"},
        )
        and _has_columns(inspector, "paper_document", {"public_id", "version", "blob_id"})
        and _has_columns(inspector, "code_repository", {"public_id", "version", "blob_id"})
        and _has_columns(inspector, "trace_link", {"public_id", "version"})
        and {
            "local_sync_outbox",
            "local_sync_state",
            "local_sync_conflict",
            "local_sync_inbox",
        }.issubset(tables)
    )
    if not has_0006:
        return detected
    detected = LOCAL_REVISIONS[5]
    agent_tables = (
        "agent_conversation",
        "agent_message",
        "agent_run",
        "agent_run_event",
        "agent_memory",
    )
    has_0007 = all(
        _has_columns(inspector, table, {"public_id", "version"}) for table in agent_tables
    ) and _has_columns(inspector, "local_sync_outbox", {"supersedes_operation_id"})
    if not has_0007:
        return detected
    detected = LOCAL_REVISIONS[6]
    if "local_artifact_version" in tables:
        detected = LOCAL_REVISIONS[7]
    if (
        "agent_analysis_job" in tables
        and "agent_analysis_artifact" in tables
        and _has_columns(inspector, "agent_conversation", {"kind"})
    ):
        detected = LOCAL_REVISIONS[8]
    else:
        return detected
    if (
        "paper_target" in tables
        and "code_target" in tables
        and "trace_review_event" in tables
        and _has_columns(
            inspector,
            "trace_link",
            {"paper_target_id", "code_target_id", "relevance"},
        )
    ):
        detected = LOCAL_REVISIONS[9]
    else:
        return detected
    if not _has_columns(inspector, "integration_config", {"agent_analysis_model"}):
        return detected
    detected = LOCAL_REVISIONS[10]
    # 0012 repaired trace_link columns that early 0010 builds never created. A DB is only
    # fully at 0012 once every agent-authored trace-link column exists.
    if _has_columns(
        inspector,
        "trace_link",
        {"artifact_id", "score_basis_json", "provenance_json", "supersedes_trace_id"},
    ):
        detected = LOCAL_REVISIONS[11]
    else:
        return detected
    # 0013 added the RAG chunk store and embedder configuration.
    if (
        {"rag_chunk", "rag_index_state"}.issubset(tables)
        and _has_columns(inspector, "integration_config", {"rag_enabled", "rag_embedder"})
    ):
        detected = LOCAL_REVISIONS[12]
    return detected


def _alembic_config(database_url: str) -> Any:
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(Path(__file__).with_name("migrations")))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def _available_revisions(config: Any) -> set[str]:
    """Revision ids whose migration script is actually present in this build.

    Packaged Desktop builds can drift: ``LOCAL_REVISIONS`` (and a persisted
    SQLite ``alembic_version``) may reference a revision whose script was not
    bundled into ``migrations/versions``. Alembic then aborts with
    ``Can't locate revision identified by '...'``. We use this set to clamp any
    stamp/upgrade target to what the running build can actually resolve.
    """

    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(config)
    return {revision.revision for revision in script.walk_revisions()}


def _highest_available(candidate: str, available: set[str]) -> str:
    """Largest LOCAL_REVISIONS entry <= ``candidate`` whose script exists."""

    ceiling = LOCAL_REVISIONS.index(candidate)
    for revision in reversed(LOCAL_REVISIONS[: ceiling + 1]):
        if revision in available:
            return revision
    return candidate


def _run_alembic(engine: Engine) -> None:
    from alembic import command

    config = _alembic_config(_database_url(engine))
    available = _available_revisions(config)
    tables = set(inspect(engine).get_table_names())
    if "project" in tables:
        detected_revision = _detect_local_revision(engine, tables)
        # Never target a revision whose script is missing from this build.
        detected_revision = _highest_available(detected_revision, available)
        current_revision = None
        if "alembic_version" in tables:
            with engine.connect() as connection:
                current_revision = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one_or_none()
        # A DB stamped to a revision this build cannot resolve (e.g. a newer dev
        # build wrote 0009 before this build shipped its script) would make the
        # upgrade below abort. Re-stamp it down to the detected, resolvable
        # revision; already-present columns/tables make the upgrade a no-op.
        current_unresolved = current_revision is not None and current_revision not in available
        current_position = (
            LOCAL_REVISIONS.index(current_revision) if current_revision in LOCAL_REVISIONS else -1
        )
        if current_unresolved:
            # ``command.stamp`` first resolves the *current* version_num to purge
            # it, which itself raises for an unresolvable id. Clear the row via
            # SQL so the subsequent stamp starts from a clean slate.
            with engine.begin() as connection:
                connection.execute(text("DELETE FROM alembic_version"))
        if (
            current_revision is None
            or current_unresolved
            or LOCAL_REVISIONS.index(detected_revision) > current_position
        ):
            command.stamp(config, detected_revision)
    command.upgrade(config, "head")


def _column_names(engine: Engine, table: str) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns(table)}


def _add_missing_columns(engine: Engine, table: str, definitions: dict[str, str]) -> None:
    existing = _column_names(engine, table)
    with engine.begin() as connection:
        for name, definition in definitions.items():
            if name not in existing:
                connection.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {definition}'))


# Trace-agent-v2 target tables from early 0010 builds used an incompatible prototype schema
# (integer ``id`` PK) instead of the current string PK. They hold only regenerable analysis
# output, so a drifted copy is dropped and left for ``metadata.create_all`` to recreate.
_DRIFTED_TARGET_TABLES = {
    "paper_target": "target_id",
    "code_target": "target_id",
    "trace_review_event": "event_id",
}


def _drop_drifted_target_tables(engine: Engine) -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table, pk_column in _DRIFTED_TARGET_TABLES.items():
            if table not in tables:
                continue
            columns = {column["name"] for column in inspector.get_columns(table)}
            if pk_column not in columns:
                connection.execute(text(f'DROP TABLE "{table}"'))


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
        "project",
        {
            "public_id": "VARCHAR(36)",
            "cloud_workspace_id": "VARCHAR(36)",
            "version": "INTEGER NOT NULL DEFAULT 1",
            "sync_mode": "VARCHAR(24) NOT NULL DEFAULT 'local_only'",
            "agent_history_sync": "BOOLEAN NOT NULL DEFAULT 1",
            "deleted_at": "DATETIME",
        },
    )
    _add_missing_columns(
        engine,
        "paper_document",
        {
            "public_id": "VARCHAR(36)",
            "version": "INTEGER NOT NULL DEFAULT 1",
            "blob_id": "VARCHAR(36)",
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
            "public_id": "VARCHAR(36)",
            "version": "INTEGER NOT NULL DEFAULT 1",
            "blob_id": "VARCHAR(36)",
            "tensor_graph_json": 'JSON NOT NULL DEFAULT \'{"nodes":[],"edges":[]}\'',
            "analysis_json": "JSON NOT NULL DEFAULT '{}'",
            "analysis_revision": "INTEGER NOT NULL DEFAULT 0",
            "analysis_version": "VARCHAR(64) NOT NULL DEFAULT ''",
            "analysis_status": "VARCHAR(24) NOT NULL DEFAULT 'pending'",
            "analysis_error": "VARCHAR(500)",
            "analysis_updated_at": "DATETIME",
            "revision": "INTEGER NOT NULL DEFAULT 1",
            "updated_at": "DATETIME",
        },
    )
    if "agent_run" in tables:
        _add_missing_columns(
            engine,
            "agent_run",
            {"capability_snapshot_json": "JSON NOT NULL DEFAULT '[]'"},
        )
    if "integration_config" in tables:
        _add_missing_columns(
            engine,
            "integration_config",
            {"agent_analysis_model": "VARCHAR(160) NOT NULL DEFAULT ''"},
        )
    if "agent_tool_request" in tables:
        _add_missing_columns(
            engine,
            "agent_tool_request",
            {
                "conversation_id": "VARCHAR(72)",
                "run_id": "VARCHAR(72)",
            },
        )
    _add_missing_columns(
        engine,
        "trace_link",
        {
            "public_id": "VARCHAR(36)",
            "version": "INTEGER NOT NULL DEFAULT 1",
            "trace_id": "VARCHAR(64)",
            "paper_document_id": "INTEGER",
            "code_repository_id": "INTEGER",
            "code_revision": "INTEGER NOT NULL DEFAULT 1",
            "static_confidence": "FLOAT NOT NULL DEFAULT 0",
            "llm_confidence": "FLOAT",
            "source": "VARCHAR(32) NOT NULL DEFAULT 'legacy'",
            "evidence_json": "JSON NOT NULL DEFAULT '[]'",
            "uncertainty_json": 'JSON NOT NULL DEFAULT \'{"level":"high","reasons":[]}\'',
            "model_info_json": "JSON",
            "fingerprint": "VARCHAR(64)",
            "status": "VARCHAR(32) NOT NULL DEFAULT 'stale'",
            "stale_reason": "VARCHAR(128) DEFAULT 'legacy_missing_version_evidence'",
            "decided_at": "DATETIME",
            "updated_at": "DATETIME",
            "artifact_id": "VARCHAR(72)",
            "paper_target_id": "VARCHAR(72)",
            "code_target_id": "VARCHAR(72)",
            "relevance": "FLOAT NOT NULL DEFAULT 0",
            "score_basis_json": "JSON NOT NULL DEFAULT '{}'",
            "provenance_json": "JSON NOT NULL DEFAULT '{}'",
            "supersedes_trace_id": "VARCHAR(64)",
        },
    )
    with engine.begin() as connection:
        for table in ("project", "paper_document", "code_repository", "trace_link"):
            connection.execute(
                text(
                    f'UPDATE "{table}" SET public_id = '
                    "lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || "
                    "substr(lower(hex(randomblob(2))),2) || '-a' || "
                    "substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6))) "
                    "WHERE public_id IS NULL"
                )
            )
        connection.execute(
            text("UPDATE code_repository SET updated_at = created_at WHERE updated_at IS NULL")
        )
        for table in ("project", "paper_document", "code_repository", "trace_link"):
            connection.execute(
                text(
                    f"CREATE UNIQUE INDEX IF NOT EXISTS ux_{table}_public_id "
                    f'ON "{table}"(public_id)'
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
    # Drop trace-target tables left in the incompatible early-0010 prototype schema so the
    # create_all below recreates them correctly (mirrors Alembic migration 0012).
    _drop_drifted_target_tables(engine)
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
