"""Add local public ids and cloud account/sync infrastructure."""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0006_cloud_accounts_sync"
down_revision = "0005_runtime_events_analysis_cache"
branch_labels = None
depends_on = None


def _uuid() -> str:
    return str(uuid4())


def _add_local_sync_columns() -> None:
    op.add_column("project", sa.Column("public_id", sa.String(36), nullable=True))
    op.add_column("project", sa.Column("cloud_workspace_id", sa.String(36), nullable=True))
    op.add_column("project", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column(
        "project",
        sa.Column("sync_mode", sa.String(24), nullable=False, server_default="local_only"),
    )
    op.add_column(
        "project",
        sa.Column("agent_history_sync", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("project", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    for table in ("paper_document", "code_repository"):
        op.add_column(table, sa.Column("public_id", sa.String(36), nullable=True))
        op.add_column(table, sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
        op.add_column(table, sa.Column("blob_id", sa.String(36), nullable=True))
    op.add_column("trace_link", sa.Column("public_id", sa.String(36), nullable=True))
    op.add_column(
        "trace_link", sa.Column("version", sa.Integer(), nullable=False, server_default="1")
    )
    connection = op.get_bind()
    for table in ("project", "paper_document", "code_repository", "trace_link"):
        ids = connection.execute(
            sa.text(f'SELECT id FROM "{table}" WHERE public_id IS NULL')
        ).scalars()
        for row_id in ids:
            connection.execute(
                sa.text(f'UPDATE "{table}" SET public_id=:value WHERE id=:id'),
                {"value": _uuid(), "id": row_id},
            )
        # SQLite cannot alter nullability in-place. Values are backfilled and
        # the application model enforces non-null; PostgreSQL gets the strict
        # database constraint used by the cloud deployment.
        if connection.dialect.name != "sqlite":
            op.alter_column(table, "public_id", nullable=False)
        op.create_index(f"ux_{table}_public_id", table, ["public_id"], unique=True)
    op.create_index("ix_project_cloud_workspace_id", "project", ["cloud_workspace_id"])
    op.create_index("ix_project_sync_mode", "project", ["sync_mode"])


def _identity_tables() -> None:
    op.create_table(
        "user_account",
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("email_normalized", sa.String(320), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("display_name", sa.String(160), nullable=False, server_default=""),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("email_verified_at", sa.DateTime(), nullable=True),
        sa.Column("is_platform_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_user_account_email_normalized", "user_account", ["email_normalized"], unique=True
    )
    op.create_index("ix_user_account_status", "user_account", ["status"])
    op.create_index("ix_user_account_is_platform_admin", "user_account", ["is_platform_admin"])
    op.create_table(
        "device",
        sa.Column("device_id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("user_account.user_id"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("client_version", sa.String(64), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_device_user_id", "device", ["user_id"])
    op.create_table(
        "auth_session",
        sa.Column("session_id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("user_account.user_id"), nullable=False),
        sa.Column("device_id", sa.String(36), sa.ForeignKey("device.device_id"), nullable=False),
        sa.Column("refresh_token_hash", sa.String(64), nullable=False),
        sa.Column("previous_refresh_token_hash", sa.String(64), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("last_ip_hash", sa.String(64), nullable=False),
        sa.Column("user_agent_summary", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("user_id", "device_id", "refresh_token_hash", "expires_at", "revoked_at"):
        op.create_index(f"ix_auth_session_{column}", "auth_session", [column])
    op.create_table(
        "workspace",
        sa.Column("workspace_id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column(
            "created_by", sa.String(36), sa.ForeignKey("user_account.user_id"), nullable=False
        ),
        sa.Column("plan", sa.String(32), nullable=False),
        sa.Column("storage_limit_bytes", sa.BigInteger(), nullable=False),
        sa.Column("workspace_seq", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "workspace_member",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "workspace_id", sa.String(36), sa.ForeignKey("workspace.workspace_id"), nullable=False
        ),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("user_account.user_id"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),
    )
    op.create_table(
        "email_token",
        sa.Column("token_id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("user_account.user_id"), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "audit_log",
        sa.Column("audit_id", sa.String(36), primary_key=True),
        sa.Column("actor_id", sa.String(36), nullable=True),
        sa.Column("workspace_id", sa.String(36), nullable=True),
        sa.Column("action", sa.String(96), nullable=False),
        sa.Column("target", sa.String(255), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "auth_rate_limit",
        sa.Column("bucket_key", sa.String(128), primary_key=True),
        sa.Column("window_started_at", sa.DateTime(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
    )


def _sync_tables() -> None:
    op.create_table(
        "cloud_project",
        sa.Column("public_id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id", sa.String(36), sa.ForeignKey("workspace.workspace_id"), nullable=False
        ),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "created_by", sa.String(36), sa.ForeignKey("user_account.user_id"), nullable=False
        ),
        sa.Column(
            "updated_by", sa.String(36), sa.ForeignKey("user_account.user_id"), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("sync_mode", sa.String(24), nullable=False),
        sa.Column("agent_history_sync", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "cloud_entity",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(72), nullable=False),
        sa.Column(
            "workspace_id", sa.String(36), sa.ForeignKey("workspace.workspace_id"), nullable=False
        ),
        sa.Column("project_public_id", sa.String(36), nullable=True),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("workspace_id", "entity_type", "public_id", name="uq_cloud_entity"),
    )
    op.create_table(
        "sync_event",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id", sa.String(36), sa.ForeignKey("workspace.workspace_id"), nullable=False
        ),
        sa.Column("workspace_seq", sa.BigInteger(), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_public_id", sa.String(72), nullable=False),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("entity_version", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("workspace_id", "workspace_seq", name="uq_sync_workspace_seq"),
    )
    op.create_table(
        "sync_receipt",
        sa.Column("receipt_id", sa.String(36), primary_key=True),
        sa.Column("client_operation_id", sa.String(72), nullable=False),
        sa.Column("device_id", sa.String(36), sa.ForeignKey("device.device_id"), nullable=False),
        sa.Column(
            "workspace_id", sa.String(36), sa.ForeignKey("workspace.workspace_id"), nullable=False
        ),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("client_operation_id", "device_id", name="uq_sync_receipt_operation"),
    )
    op.create_table(
        "sync_device_cursor",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("device_id", sa.String(36), sa.ForeignKey("device.device_id"), nullable=False),
        sa.Column(
            "workspace_id", sa.String(36), sa.ForeignKey("workspace.workspace_id"), nullable=False
        ),
        sa.Column("last_pulled_seq", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("device_id", "workspace_id", name="uq_sync_device_cursor"),
    )
    op.create_table(
        "entity_tombstone",
        sa.Column("tombstone_id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id", sa.String(36), sa.ForeignKey("workspace.workspace_id"), nullable=False
        ),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_public_id", sa.String(72), nullable=False),
        sa.Column("deleted_version", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "workspace_id", "entity_type", "entity_public_id", name="uq_entity_tombstone"
        ),
    )
    op.create_table(
        "blob_object",
        sa.Column("blob_id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id", sa.String(36), sa.ForeignKey("workspace.workspace_id"), nullable=False
        ),
        sa.Column("project_public_id", sa.String(36), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(160), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column(
            "created_by", sa.String(36), sa.ForeignKey("user_account.user_id"), nullable=False
        ),
        sa.Column("reference_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("workspace_id", "sha256", name="uq_blob_workspace_hash"),
    )
    op.create_table(
        "background_job",
        sa.Column("job_id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=True),
        sa.Column("job_type", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False, unique=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "local_sync_outbox",
        sa.Column("client_operation_id", sa.String(72), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("device_id", sa.String(36), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_public_id", sa.String(72), nullable=False),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("base_version", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "local_sync_state",
        sa.Column("workspace_id", sa.String(36), primary_key=True),
        sa.Column("device_id", sa.String(36), nullable=False),
        sa.Column("last_pulled_seq", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "local_sync_conflict",
        sa.Column("conflict_id", sa.String(36), primary_key=True),
        sa.Column("client_operation_id", sa.String(72), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_public_id", sa.String(72), nullable=False),
        sa.Column("local_payload_json", sa.JSON(), nullable=False),
        sa.Column("remote_payload_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "local_sync_inbox",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("workspace_seq", sa.BigInteger(), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_public_id", sa.String(72), nullable=False),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("entity_version", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("applied_at", sa.DateTime(), nullable=False),
    )


def _local_sync_tables() -> None:
    op.create_table(
        "local_sync_outbox",
        sa.Column("client_operation_id", sa.String(72), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("device_id", sa.String(36), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_public_id", sa.String(72), nullable=False),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("base_version", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "local_sync_state",
        sa.Column("workspace_id", sa.String(36), primary_key=True),
        sa.Column("device_id", sa.String(36), nullable=False),
        sa.Column("last_pulled_seq", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "local_sync_conflict",
        sa.Column("conflict_id", sa.String(36), primary_key=True),
        sa.Column("client_operation_id", sa.String(72), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_public_id", sa.String(72), nullable=False),
        sa.Column("local_payload_json", sa.JSON(), nullable=False),
        sa.Column("remote_payload_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "local_sync_inbox",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("workspace_seq", sa.BigInteger(), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_public_id", sa.String(72), nullable=False),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("entity_version", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("applied_at", sa.DateTime(), nullable=False),
    )


def upgrade() -> None:
    _add_local_sync_columns()
    if op.get_bind().dialect.name == "sqlite":
        _local_sync_tables()
    else:
        _identity_tables()
        _sync_tables()


def downgrade() -> None:
    cloud_tables = (
        "background_job",
        "blob_object",
        "entity_tombstone",
        "sync_device_cursor",
        "sync_receipt",
        "sync_event",
        "cloud_entity",
        "cloud_project",
        "auth_rate_limit",
        "audit_log",
        "email_token",
        "workspace_member",
        "workspace",
        "auth_session",
        "device",
        "user_account",
    )
    for table in (
        "local_sync_inbox",
        "local_sync_conflict",
        "local_sync_state",
        "local_sync_outbox",
    ):
        op.drop_table(table)
    if op.get_bind().dialect.name != "sqlite":
        for table in cloud_tables:
            op.drop_table(table)
    for table in ("trace_link", "code_repository", "paper_document", "project"):
        op.drop_index(f"ux_{table}_public_id", table_name=table)
    op.drop_column("trace_link", "version")
    op.drop_column("trace_link", "public_id")
    for table in ("code_repository", "paper_document"):
        for column in ("blob_id", "version", "public_id"):
            op.drop_column(table, column)
    for column in (
        "deleted_at",
        "agent_history_sync",
        "sync_mode",
        "version",
        "cloud_workspace_id",
        "public_id",
    ):
        op.drop_column("project", column)
