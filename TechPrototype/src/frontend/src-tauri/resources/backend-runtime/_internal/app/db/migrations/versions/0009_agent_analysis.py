"""Add Agent-owned analysis jobs and derived artifacts."""

import sqlalchemy as sa
from alembic import op

revision = "0009_agent_analysis"
down_revision = "0008_local_artifact_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_conversation",
        sa.Column("kind", sa.String(24), nullable=False, server_default="interactive"),
    )
    op.create_index("ix_agent_conversation_kind", "agent_conversation", ["kind"])
    op.create_table(
        "agent_analysis_job",
        sa.Column("job_id", sa.String(72), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id"), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("paper_document_id", sa.Integer(), sa.ForeignKey("paper_document.id")),
        sa.Column(
            "code_repository_id", sa.Integer(), sa.ForeignKey("code_repository.id"), nullable=False
        ),
        sa.Column("code_revision", sa.Integer(), nullable=False),
        sa.Column("root_symbol", sa.String(500)),
        sa.Column("requested_depth", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("agent_run_id", sa.String(72), sa.ForeignKey("agent_run.run_id")),
        sa.Column("artifact_id", sa.String(72)),
        sa.Column("fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("progress_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("error_code", sa.String(128)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
    )
    for column in (
        "project_id",
        "kind",
        "status",
        "paper_document_id",
        "code_repository_id",
        "code_revision",
        "agent_run_id",
        "artifact_id",
        "fingerprint",
    ):
        op.create_index(f"ix_agent_analysis_job_{column}", "agent_analysis_job", [column])
    op.create_table(
        "agent_analysis_artifact",
        sa.Column("artifact_id", sa.String(72), primary_key=True),
        sa.Column(
            "job_id", sa.String(72), sa.ForeignKey("agent_analysis_job.job_id"), nullable=False
        ),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id"), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("paper_document_id", sa.Integer(), sa.ForeignKey("paper_document.id")),
        sa.Column(
            "code_repository_id", sa.Integer(), sa.ForeignKey("code_repository.id"), nullable=False
        ),
        sa.Column("code_revision", sa.Integer(), nullable=False),
        sa.Column("agent_run_id", sa.String(72), sa.ForeignKey("agent_run.run_id"), nullable=False),
        sa.Column("model_info_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("capability_snapshot_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("fingerprint", name="uq_agent_analysis_artifact_fp"),
    )
    for column in (
        "job_id",
        "project_id",
        "kind",
        "paper_document_id",
        "code_repository_id",
        "code_revision",
        "agent_run_id",
        "fingerprint",
        "is_current",
    ):
        op.create_index(f"ix_agent_analysis_artifact_{column}", "agent_analysis_artifact", [column])


def downgrade() -> None:
    op.drop_table("agent_analysis_artifact")
    op.drop_table("agent_analysis_job")
    op.drop_index("ix_agent_conversation_kind", table_name="agent_conversation")
    op.drop_column("agent_conversation", "kind")
