"""RAG retrieval layer: embedded chunk store, per-scope index state, embedder config.

Three additions, all derived-data or configuration — no existing row is rewritten:

1. ``rag_chunk`` holds embedded retrieval units for the paper, code, and trace scopes. The
   vector lives in a TEXT column as base64 float32: SQLite has no vector type, and the
   corpora here (thousands of chunks) are small enough that an exact in-Python cosine scan
   is faster than adding a native index to the PyInstaller sidecar.
2. ``rag_index_state`` records which generation of each source is indexed, so a rebuild is
   skipped when the paper content hash / code revision has not moved.
3. ``integration_config.rag_*`` stores the embedder choice. Default is the offline local
   embedder, so retrieval works with no API key and no network.

Idempotent: every step checks for prior existence, matching the other local migrations that
must tolerate databases created by ``create_all`` in early Desktop builds.
"""

import sqlalchemy as sa
from alembic import op

revision = "0013_rag_index"
down_revision = "0012_trace_link_repair"
branch_labels = None
depends_on = None


_RAG_CONFIG_COLUMNS: tuple[sa.Column, ...] = (
    sa.Column("rag_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.Column("rag_embedder", sa.String(16), nullable=False, server_default="local"),
    sa.Column("rag_base_url", sa.String(500), nullable=False, server_default=""),
    sa.Column("rag_api_key", sa.Text(), nullable=False, server_default=""),
    sa.Column("rag_model", sa.String(160), nullable=False, server_default=""),
    sa.Column("rag_dimensions", sa.Integer(), nullable=False, server_default="512"),
    sa.Column("rag_timeout_seconds", sa.Float(), nullable=False, server_default="30"),
)


def _create_rag_chunk() -> None:
    op.create_table(
        "rag_chunk",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id"), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("source_key", sa.String(128), nullable=False),
        sa.Column("ref", sa.String(500), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", sa.Text(), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embedder", sa.String(64), nullable=False, server_default="local"),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("project_id", "scope", "source_key"):
        op.create_index(f"ix_rag_chunk_{column}", "rag_chunk", [column])


def _create_rag_index_state() -> None:
    op.create_table(
        "rag_index_state",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id"), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("source_key", sa.String(128), nullable=False, server_default=""),
        sa.Column("embedder", sa.String(64), nullable=False, server_default="local"),
        sa.Column("model", sa.String(160), nullable=False, server_default=""),
        sa.Column("dimensions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("error", sa.String(500)),
        sa.Column("built_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("project_id", "scope", name="uq_rag_index_project_scope"),
    )
    for column in ("project_id", "scope", "status"):
        op.create_index(f"ix_rag_index_state_{column}", "rag_index_state", [column])


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "rag_chunk" not in tables:
        _create_rag_chunk()
    if "rag_index_state" not in tables:
        _create_rag_index_state()
    if "integration_config" in tables:
        existing = {column["name"] for column in inspector.get_columns("integration_config")}
        for column in _RAG_CONFIG_COLUMNS:
            if column.name not in existing:
                op.add_column("integration_config", column)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "rag_index_state" in tables:
        op.drop_table("rag_index_state")
    if "rag_chunk" in tables:
        op.drop_table("rag_chunk")
    if "integration_config" in tables:
        existing = {column["name"] for column in inspector.get_columns("integration_config")}
        for column in _RAG_CONFIG_COLUMNS:
            if column.name in existing:
                op.drop_column("integration_config", column.name)
