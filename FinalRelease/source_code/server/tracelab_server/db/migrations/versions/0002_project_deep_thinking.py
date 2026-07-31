"""Persist the project-level confidence scoring mode in cloud projects."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_project_deep_thinking"
down_revision: Union[str, None] = "0001_server_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cloud_project",
        sa.Column(
            "agent_deep_thinking",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("cloud_project", "agent_deep_thinking")
