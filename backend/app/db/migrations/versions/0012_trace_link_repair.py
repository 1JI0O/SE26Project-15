"""Repair trace-agent-v2 schema drift left by early 0010_trace_targets builds.

Two independent drifts are repaired here, both caused by databases that ran an early
version of ``0010_trace_targets`` and are already stamped past it (so Alembic never
re-runs 0010):

1. ``trace_link`` is missing the agent columns ``artifact_id`` / ``score_basis_json`` /
   ``provenance_json`` / ``supersedes_trace_id``. Writing an Agent trace candidate then
   fails with ``OperationalError: no such column: trace_link.artifact_id`` at the first
   publish, producing zero trace links.

2. ``paper_target`` / ``code_target`` / ``trace_review_event`` exist but with an older,
   incompatible prototype schema (integer ``id`` PK + ``is_interactive`` etc.) instead of
   the current string ``target_id`` / ``event_id`` PK schema. Persisting an artifact then
   fails with ``OperationalError: no such column: paper_target.target_id``.

The target tables hold only regenerable analysis output (upserted by fingerprint on every
run), so drifted copies are dropped and recreated with the canonical schema. This migration
is idempotent: a no-op on databases created by the corrected 0010 script.
"""

import sqlalchemy as sa
from alembic import op

revision = "0012_trace_link_repair"
down_revision = "0011_agent_analysis_model"
branch_labels = None
depends_on = None


_TRACE_LINK_COLUMNS: dict[str, tuple[sa.Column, bool]] = {
    "artifact_id": (sa.Column("artifact_id", sa.String(72)), True),
    "paper_target_id": (sa.Column("paper_target_id", sa.String(72)), True),
    "code_target_id": (sa.Column("code_target_id", sa.String(72)), True),
    "relevance": (
        sa.Column("relevance", sa.Float(), nullable=False, server_default="0"),
        False,
    ),
    "score_basis_json": (
        sa.Column("score_basis_json", sa.JSON(), nullable=False, server_default="{}"),
        False,
    ),
    "provenance_json": (
        sa.Column("provenance_json", sa.JSON(), nullable=False, server_default="{}"),
        False,
    ),
    "supersedes_trace_id": (sa.Column("supersedes_trace_id", sa.String(64)), True),
}


def _repair_trace_link(inspector: sa.Inspector) -> None:
    existing = {column["name"] for column in inspector.get_columns("trace_link")}
    existing_indexes = {index["name"] for index in inspector.get_indexes("trace_link")}
    for name, (column, indexed) in _TRACE_LINK_COLUMNS.items():
        if name not in existing:
            op.add_column("trace_link", column)
        index_name = f"ix_trace_link_{name}"
        if indexed and index_name not in existing_indexes:
            op.create_index(index_name, "trace_link", [name])


def _create_paper_target() -> None:
    op.create_table(
        "paper_target",
        sa.Column("target_id", sa.String(72), primary_key=True),
        sa.Column("public_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id"), nullable=False),
        sa.Column(
            "artifact_id",
            sa.String(72),
            sa.ForeignKey("agent_analysis_artifact.artifact_id"),
            nullable=False,
        ),
        sa.Column(
            "paper_document_id",
            sa.Integer(),
            sa.ForeignKey("paper_document.id"),
            nullable=False,
        ),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("block_id", sa.String(255), nullable=False),
        sa.Column("section_path_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("occurrence", sa.Integer(), nullable=False),
        sa.Column("char_start", sa.Integer()),
        sa.Column("char_end", sa.Integer()),
        sa.Column("quote_hash", sa.String(64), nullable=False),
        sa.Column("bbox_json", sa.JSON()),
        sa.Column("asset_path", sa.String(1000)),
        sa.Column("salience", sa.Float(), nullable=False, server_default="0"),
        sa.Column("salience_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("anchor_status", sa.String(32), nullable=False, server_default="validated"),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint("fingerprint", name="uq_paper_target_fingerprint"),
    )
    for column in (
        "public_id", "project_id", "artifact_id", "paper_document_id",
        "target_type", "block_id", "quote_hash", "anchor_status", "fingerprint",
    ):
        op.create_index(f"ix_paper_target_{column}", "paper_target", [column])


def _create_code_target() -> None:
    op.create_table(
        "code_target",
        sa.Column("target_id", sa.String(72), primary_key=True),
        sa.Column("public_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id"), nullable=False),
        sa.Column(
            "artifact_id",
            sa.String(72),
            sa.ForeignKey("agent_analysis_artifact.artifact_id"),
            nullable=False,
        ),
        sa.Column(
            "code_repository_id",
            sa.Integer(),
            sa.ForeignKey("code_repository.id"),
            nullable=False,
        ),
        sa.Column("code_revision", sa.Integer(), nullable=False),
        sa.Column("path", sa.String(1000), nullable=False),
        sa.Column("symbol_id", sa.String(500)),
        sa.Column("line_start", sa.Integer(), nullable=False),
        sa.Column("line_end", sa.Integer(), nullable=False),
        sa.Column("column_start", sa.Integer()),
        sa.Column("column_end", sa.Integer()),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("occurrence", sa.Integer(), nullable=False),
        sa.Column("code_quote_hash", sa.String(64), nullable=False),
        sa.Column("role", sa.String(64), nullable=False),
        sa.Column("salience", sa.Float(), nullable=False, server_default="0"),
        sa.Column("salience_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("anchor_status", sa.String(32), nullable=False, server_default="validated"),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint("fingerprint", name="uq_code_target_fingerprint"),
    )
    for column in (
        "public_id", "project_id", "artifact_id", "code_repository_id", "code_revision",
        "path", "symbol_id", "code_quote_hash", "role", "anchor_status", "fingerprint",
    ):
        op.create_index(f"ix_code_target_{column}", "code_target", [column])


def _create_trace_review_event() -> None:
    op.create_table(
        "trace_review_event",
        sa.Column("event_id", sa.String(72), primary_key=True),
        sa.Column("public_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id"), nullable=False),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("actor_type", sa.String(24), nullable=False),
        sa.Column("actor_ref", sa.String(160)),
        sa.Column("before_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("after_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("job_id", sa.String(72)),
        sa.Column("run_id", sa.String(72)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("public_id"),
    )
    for column in ("public_id", "project_id", "trace_id"):
        op.create_index(f"ix_trace_review_event_{column}", "trace_review_event", [column])


# table -> (canonical PK column that early prototype schemas lack, recreate fn)
_TARGET_TABLES = {
    "paper_target": ("target_id", _create_paper_target),
    "code_target": ("target_id", _create_code_target),
    "trace_review_event": ("event_id", _create_trace_review_event),
}


def _repair_target_tables(inspector: sa.Inspector) -> None:
    tables = set(inspector.get_table_names())
    for table, (pk_column, create) in _TARGET_TABLES.items():
        if table not in tables:
            # Missing entirely (chain never reached 0010's create): create fresh.
            create()
            continue
        columns = {column["name"] for column in inspector.get_columns(table)}
        if pk_column not in columns:
            # Drifted prototype schema. Rows are regenerable analysis output; drop + recreate.
            op.drop_table(table)
            create()


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    _repair_trace_link(inspector)
    _repair_target_tables(inspector)


def downgrade() -> None:
    # No-op: 0010 owns this schema on a clean chain; this migration only repairs drift.
    pass
