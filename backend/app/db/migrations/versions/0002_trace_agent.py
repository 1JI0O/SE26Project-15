"""Add versioned traces and audited Agent confirmations."""

import sqlalchemy as sa
from alembic import op

revision = "0002_trace_agent"
down_revision = "0001_legacy_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("paper_document") as batch:
        batch.add_column(
            sa.Column("parser", sa.String(64), nullable=False, server_default="legacy")
        )
        batch.add_column(
            sa.Column("parser_version", sa.String(128), nullable=False, server_default="")
        )
        batch.add_column(
            sa.Column(
                "parse_status",
                sa.String(32),
                nullable=False,
                server_default="succeeded",
            )
        )
        batch.add_column(
            sa.Column("content_hash", sa.String(64), nullable=False, server_default="")
        )
        batch.add_column(sa.Column("pages_json", sa.JSON(), nullable=False, server_default="[]"))

    with op.batch_alter_table("code_repository") as batch:
        batch.add_column(
            sa.Column(
                "tensor_graph_json",
                sa.JSON(),
                nullable=False,
                server_default='{"nodes":[],"edges":[]}',
            )
        )
        batch.add_column(sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))

    trace_columns = [
        sa.Column("trace_id", sa.String(64), nullable=True),
        sa.Column("paper_document_id", sa.Integer(), nullable=True),
        sa.Column("code_repository_id", sa.Integer(), nullable=True),
        sa.Column("code_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("static_confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("llm_confidence", sa.Float(), nullable=True),
        sa.Column("source", sa.String(32), nullable=False, server_default="legacy"),
        sa.Column("evidence_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "uncertainty_json",
            sa.JSON(),
            nullable=False,
            server_default='{"level":"high","reasons":[]}',
        ),
        sa.Column("model_info_json", sa.JSON(), nullable=True),
        sa.Column("fingerprint", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="stale"),
        sa.Column("stale_reason", sa.String(128), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    ]
    with op.batch_alter_table("trace_link") as batch:
        for column in trace_columns:
            batch.add_column(column)
        batch.create_foreign_key("fk_trace_paper", "paper_document", ["paper_document_id"], ["id"])
        batch.create_foreign_key("fk_trace_code", "code_repository", ["code_repository_id"], ["id"])

    op.execute("UPDATE code_repository SET updated_at = created_at WHERE updated_at IS NULL")
    with op.batch_alter_table("code_repository") as batch:
        batch.alter_column("updated_at", nullable=False)
    op.execute(
        "UPDATE trace_link SET trace_id = 'trace-legacy-' || id, "
        "fingerprint = 'legacy-' || id, static_confidence = confidence, "
        "source = 'legacy', status = 'stale', "
        "stale_reason = 'legacy_missing_version_evidence', updated_at = created_at"
    )
    with op.batch_alter_table("trace_link") as batch:
        batch.alter_column("trace_id", nullable=False)
        batch.alter_column("fingerprint", nullable=False)
        batch.alter_column("updated_at", nullable=False)
        batch.create_unique_constraint("uq_trace_link_trace_id", ["trace_id"])
        batch.create_unique_constraint("uq_trace_link_fingerprint", ["fingerprint"])
        batch.create_index("ix_trace_link_status", ["status"])
        batch.create_index("ix_trace_link_paper_document_id", ["paper_document_id"])
        batch.create_index("ix_trace_link_code_repository_id", ["code_repository_id"])

    op.create_table(
        "agent_tool_request",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("confirmation_id", sa.String(72), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id"), nullable=False),
        sa.Column("tool_name", sa.String(64), nullable=False),
        sa.Column("private_arguments_json", sa.JSON(), nullable=False),
        sa.Column("parameter_summary_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("user_decision", sa.String(16), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error_summary", sa.String(500), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("executed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("confirmation_id", name="uq_agent_confirmation_id"),
    )
    op.create_index("ix_agent_tool_request_project_id", "agent_tool_request", ["project_id"])
    op.create_index(
        "ix_agent_tool_request_confirmation_id",
        "agent_tool_request",
        ["confirmation_id"],
    )
    op.create_index("ix_agent_tool_request_status", "agent_tool_request", ["status"])


def downgrade() -> None:
    op.drop_table("agent_tool_request")
    with op.batch_alter_table("trace_link") as batch:
        for name in [
            "updated_at",
            "decided_at",
            "stale_reason",
            "status",
            "fingerprint",
            "model_info_json",
            "uncertainty_json",
            "evidence_json",
            "source",
            "llm_confidence",
            "static_confidence",
            "code_revision",
            "code_repository_id",
            "paper_document_id",
            "trace_id",
        ]:
            batch.drop_column(name)
    with op.batch_alter_table("code_repository") as batch:
        batch.drop_column("updated_at")
        batch.drop_column("revision")
        batch.drop_column("tensor_graph_json")
    with op.batch_alter_table("paper_document") as batch:
        batch.drop_column("pages_json")
        batch.drop_column("content_hash")
        batch.drop_column("parse_status")
        batch.drop_column("parser_version")
        batch.drop_column("parser")
