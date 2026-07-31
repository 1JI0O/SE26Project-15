"""Preserve immutable file versions downloaded to local devices."""

import sqlalchemy as sa
from alembic import op

revision = "0008_local_artifact_versions"
down_revision = "0007_cloud_consistency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "local_artifact_version",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id"), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_public_id", sa.String(36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("blob_id", sa.String(36), nullable=True),
        sa.Column("cloud_version_id", sa.String(36), nullable=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("storage_path", sa.String(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "entity_type",
            "entity_public_id",
            "version_number",
            name="uq_local_artifact_version",
        ),
    )


def downgrade() -> None:
    op.drop_table("local_artifact_version")
