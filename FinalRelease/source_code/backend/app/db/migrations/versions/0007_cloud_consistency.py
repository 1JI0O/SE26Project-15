"""Add safe blob references, immutable artifacts, and device project bindings."""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0007_cloud_consistency"
down_revision = "0006_cloud_accounts_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    connection = op.get_bind()
    for table in (
        "agent_conversation",
        "agent_message",
        "agent_run",
        "agent_run_event",
        "agent_memory",
    ):
        op.add_column(table, sa.Column("public_id", sa.String(36), nullable=True))
        op.add_column(table, sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
        identity_column = "id"
        if table == "agent_conversation":
            identity_column = "conversation_id"
        elif table == "agent_run":
            identity_column = "run_id"
        elif table == "agent_memory":
            identity_column = "memory_id"
        rows = connection.execute(
            sa.text(f'SELECT "{identity_column}" FROM "{table}" WHERE public_id IS NULL')
        ).scalars()
        for row_id in rows:
            connection.execute(
                sa.text(
                    f'UPDATE "{table}" SET public_id=:public_id WHERE "{identity_column}"=:row_id'
                ),
                {"public_id": str(uuid4()), "row_id": row_id},
            )
        if dialect != "sqlite":
            op.alter_column(table, "public_id", nullable=False)
        op.create_index(f"ux_{table}_public_id", table, ["public_id"], unique=True)
    if dialect == "sqlite":
        op.add_column(
            "local_sync_outbox",
            sa.Column("supersedes_operation_id", sa.String(72), nullable=True),
        )
        op.create_index(
            "ix_local_sync_outbox_supersedes_operation_id",
            "local_sync_outbox",
            ["supersedes_operation_id"],
        )
        return
    op.create_table(
        "blob_content",
        sa.Column("content_id", sa.String(36), primary_key=True),
        sa.Column("sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(160), nullable=False),
        sa.Column("storage_key", sa.String(255), nullable=False),
        sa.Column("physical_ref_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_blob_content_sha256", "blob_content", ["sha256"], unique=True)
    op.add_column("blob_object", sa.Column("content_id", sa.String(36), nullable=True))
    if dialect != "sqlite":
        op.create_foreign_key(
            "fk_blob_object_content",
            "blob_object",
            "blob_content",
            ["content_id"],
            ["content_id"],
        )
    op.create_index("ix_blob_object_content_id", "blob_object", ["content_id"])
    op.create_table(
        "artifact_version",
        sa.Column("version_id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspace.workspace_id"),
            nullable=False,
        ),
        sa.Column("project_public_id", sa.String(36), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_public_id", sa.String(36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("blob_id", sa.String(36), sa.ForeignKey("blob_object.blob_id"), nullable=False),
        sa.Column(
            "created_by",
            sa.String(36),
            sa.ForeignKey("user_account.user_id"),
            nullable=False,
        ),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("source_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "workspace_id",
            "entity_type",
            "entity_public_id",
            "version_number",
            name="uq_artifact_version_number",
        ),
    )
    op.create_table(
        "blob_reference",
        sa.Column("reference_id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspace.workspace_id"),
            nullable=False,
        ),
        sa.Column("project_public_id", sa.String(36), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_public_id", sa.String(36), nullable=False),
        sa.Column(
            "artifact_version_id",
            sa.String(36),
            sa.ForeignKey("artifact_version.version_id"),
            nullable=True,
        ),
        sa.Column("blob_id", sa.String(36), sa.ForeignKey("blob_object.blob_id"), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "workspace_id",
            "project_public_id",
            "entity_type",
            "entity_public_id",
            "blob_id",
            name="uq_blob_reference_target",
        ),
    )
    op.create_table(
        "upload_session",
        sa.Column("session_id", sa.String(36), primary_key=True),
        sa.Column(
            "blob_id",
            sa.String(36),
            sa.ForeignKey("blob_object.blob_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("uploaded_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "device_project_binding",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("device_id", sa.String(36), sa.ForeignKey("device.device_id"), nullable=False),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspace.workspace_id"),
            nullable=False,
        ),
        sa.Column("project_public_id", sa.String(36), nullable=False),
        sa.Column("sync_mode", sa.String(24), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("device_id", "project_public_id", name="uq_device_project_binding"),
    )
    op.add_column(
        "local_sync_outbox",
        sa.Column("supersedes_operation_id", sa.String(72), nullable=True),
    )
    op.create_index(
        "ix_local_sync_outbox_supersedes_operation_id",
        "local_sync_outbox",
        ["supersedes_operation_id"],
    )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    op.drop_index("ix_local_sync_outbox_supersedes_operation_id", table_name="local_sync_outbox")
    op.drop_column("local_sync_outbox", "supersedes_operation_id")
    if dialect != "sqlite":
        for table in (
            "device_project_binding",
            "upload_session",
            "blob_reference",
            "artifact_version",
        ):
            op.drop_table(table)
        op.drop_index("ix_blob_object_content_id", table_name="blob_object")
        op.drop_constraint("fk_blob_object_content", "blob_object", type_="foreignkey")
        op.drop_column("blob_object", "content_id")
        op.drop_index("ix_blob_content_sha256", table_name="blob_content")
        op.drop_table("blob_content")
    for table in (
        "agent_memory",
        "agent_run_event",
        "agent_run",
        "agent_message",
        "agent_conversation",
    ):
        op.drop_index(f"ux_{table}_public_id", table_name=table)
        op.drop_column(table, "version")
        op.drop_column(table, "public_id")
