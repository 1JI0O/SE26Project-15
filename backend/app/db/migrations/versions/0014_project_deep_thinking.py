"""Per-project deep-thinking toggle for the trace agent's confidence scoring.

``project.agent_deep_thinking`` decides whether the trace agent is asked to score the six
confidence dimensions (change directness, causal reachability, requirement support, trace
support, verification support, context coverage) and the server recomputes ``confidence``
from the weighted formula, or whether the agent simply reports ``confidence`` directly.

Default is false: the multi-dimensional pass costs extra reasoning per candidate and makes
the first publish batch slower, so existing projects keep the original single-score behaviour
until a user opts in.

Idempotent — the column check matches the other local migrations, which must tolerate
databases created by ``create_all`` in early Desktop builds.
"""

import sqlalchemy as sa
from alembic import op

revision = "0014_project_deep_thinking"
down_revision = "0013_rag_index"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return False
    return column in {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    if not _has_column("project", "agent_deep_thinking"):
        op.add_column(
            "project",
            sa.Column(
                "agent_deep_thinking",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    if _has_column("project", "agent_deep_thinking"):
        op.drop_column("project", "agent_deep_thinking")
