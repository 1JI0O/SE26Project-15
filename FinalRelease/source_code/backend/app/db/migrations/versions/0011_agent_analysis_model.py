"""Add optional stronger analysis model to the integration config."""

import sqlalchemy as sa
from alembic import op

revision = "0011_agent_analysis_model"
down_revision = "0010_trace_targets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "integration_config",
        sa.Column("agent_analysis_model", sa.String(160), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("integration_config", "agent_analysis_model")
