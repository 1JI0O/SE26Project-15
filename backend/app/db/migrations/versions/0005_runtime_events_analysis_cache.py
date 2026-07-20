"""Add Agent run events, capability settings, and repository analysis cache."""

import sqlalchemy as sa
from alembic import op

revision = "0005_runtime_events_analysis_cache"
down_revision = "0004_agent_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Alembic creates version_num as VARCHAR(32), while this revision id is 34
    # characters. Widen it before Alembic records the completed revision.
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("alembic_version") as batch:
            batch.alter_column(
                "version_num",
                existing_type=sa.String(32),
                type_=sa.String(64),
                nullable=False,
            )
    else:
        op.alter_column(
            "alembic_version",
            "version_num",
            existing_type=sa.String(32),
            type_=sa.String(64),
            nullable=False,
        )
    op.add_column(
        "agent_run",
        sa.Column("capability_snapshot_json", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.create_table(
        "agent_run_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(72), nullable=False),
        sa.Column("run_id", sa.String(72), sa.ForeignKey("agent_run.run_id"), nullable=False),
        sa.Column(
            "conversation_id",
            sa.String(72),
            sa.ForeignKey("agent_conversation.conversation_id"),
            nullable=False,
        ),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("event_id", name="uq_agent_run_event_id"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_agent_run_event_sequence"),
    )
    for column in (
        "event_id",
        "run_id",
        "conversation_id",
        "project_id",
        "event_type",
        "created_at",
    ):
        op.create_index(f"ix_agent_run_event_{column}", "agent_run_event", [column])

    op.create_table(
        "agent_capability_setting",
        sa.Column("capability_id", sa.String(160), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("trusted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("config_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_agent_capability_setting_enabled",
        "agent_capability_setting",
        ["enabled"],
    )
    op.create_index(
        "ix_agent_capability_setting_trusted",
        "agent_capability_setting",
        ["trusted"],
    )

    op.add_column(
        "code_repository",
        sa.Column("analysis_json", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "code_repository",
        sa.Column("analysis_revision", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "code_repository",
        sa.Column("analysis_version", sa.String(64), nullable=False, server_default=""),
    )
    op.add_column(
        "code_repository",
        sa.Column("analysis_status", sa.String(24), nullable=False, server_default="pending"),
    )
    op.add_column(
        "code_repository",
        sa.Column("analysis_error", sa.String(500), nullable=True),
    )
    op.add_column(
        "code_repository",
        sa.Column("analysis_updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_code_repository_analysis_status",
        "code_repository",
        ["analysis_status"],
    )

    op.create_table(
        "repository_analysis_job",
        sa.Column("job_id", sa.String(72), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id"), nullable=False),
        sa.Column(
            "repository_id",
            sa.Integer(),
            sa.ForeignKey("code_repository.id"),
            nullable=False,
        ),
        sa.Column("repository_revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("targets_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("error_summary", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    for column in ("project_id", "repository_id", "repository_revision", "status"):
        op.create_index(
            f"ix_repository_analysis_job_{column}",
            "repository_analysis_job",
            [column],
        )


def downgrade() -> None:
    op.drop_table("repository_analysis_job")
    op.drop_index("ix_code_repository_analysis_status", table_name="code_repository")
    for column in (
        "analysis_updated_at",
        "analysis_error",
        "analysis_status",
        "analysis_version",
        "analysis_revision",
        "analysis_json",
    ):
        op.drop_column("code_repository", column)
    op.drop_table("agent_capability_setting")
    op.drop_table("agent_run_event")
    op.drop_column("agent_run", "capability_snapshot_json")
