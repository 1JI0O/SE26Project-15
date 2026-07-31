"""Add fragment-level trace targets, review events, and trace-link anchoring columns."""

import sqlalchemy as sa
from alembic import op

revision = "0010_trace_targets"
down_revision = "0009_agent_analysis"
branch_labels = None
depends_on = None


def upgrade() -> None:
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
        "public_id",
        "project_id",
        "artifact_id",
        "paper_document_id",
        "target_type",
        "block_id",
        "quote_hash",
        "anchor_status",
        "fingerprint",
    ):
        op.create_index(f"ix_paper_target_{column}", "paper_target", [column])
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
        "public_id",
        "project_id",
        "artifact_id",
        "code_repository_id",
        "code_revision",
        "path",
        "symbol_id",
        "code_quote_hash",
        "role",
        "anchor_status",
        "fingerprint",
    ):
        op.create_index(f"ix_code_target_{column}", "code_target", [column])
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

    op.add_column("trace_link", sa.Column("artifact_id", sa.String(72)))
    op.add_column("trace_link", sa.Column("paper_target_id", sa.String(72)))
    op.add_column("trace_link", sa.Column("code_target_id", sa.String(72)))
    op.add_column(
        "trace_link", sa.Column("relevance", sa.Float(), nullable=False, server_default="0")
    )
    op.add_column(
        "trace_link", sa.Column("score_basis_json", sa.JSON(), nullable=False, server_default="{}")
    )
    op.add_column(
        "trace_link", sa.Column("provenance_json", sa.JSON(), nullable=False, server_default="{}")
    )
    op.add_column("trace_link", sa.Column("supersedes_trace_id", sa.String(64)))
    for column in ("artifact_id", "paper_target_id", "code_target_id", "supersedes_trace_id"):
        op.create_index(f"ix_trace_link_{column}", "trace_link", [column])


def downgrade() -> None:
    for column in ("artifact_id", "paper_target_id", "code_target_id", "supersedes_trace_id"):
        op.drop_index(f"ix_trace_link_{column}", table_name="trace_link")
    for column in (
        "supersedes_trace_id",
        "provenance_json",
        "score_basis_json",
        "relevance",
        "code_target_id",
        "paper_target_id",
        "artifact_id",
    ):
        op.drop_column("trace_link", column)
    op.drop_table("trace_review_event")
    op.drop_table("code_target")
    op.drop_table("paper_target")
