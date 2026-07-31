"""Optional LanceDB vector-store backend selection on integration settings.

Adds ``integration_config.rag_vector_store`` (``sqlite`` | ``lancedb``). Default remains
``sqlite`` so existing installs keep the exact in-Python cosine scan with no optional
deps. Selecting ``lancedb`` requires the backend ``rag`` extra and invalidates indexes
on change (handled in the settings service, not here).

Idempotent — column check matches the other local migrations that must tolerate
databases created by ``create_all`` in early Desktop builds.
"""

import sqlalchemy as sa
from alembic import op

revision = "0015_rag_vector_store"
down_revision = "0014_project_deep_thinking"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return False
    return column in {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    if "integration_config" in sa.inspect(op.get_bind()).get_table_names() and not _has_column(
        "integration_config", "rag_vector_store"
    ):
        op.add_column(
            "integration_config",
            sa.Column(
                "rag_vector_store",
                sa.String(16),
                nullable=False,
                server_default="sqlite",
            ),
        )


def downgrade() -> None:
    if _has_column("integration_config", "rag_vector_store"):
        op.drop_column("integration_config", "rag_vector_store")
