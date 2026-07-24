"""Add application-managed Agent and MinerU settings."""

import sqlalchemy as sa
from alembic import op

revision = "0003_integration_config"
down_revision = "0002_trace_agent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integration_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("agent_base_url", sa.String(500), nullable=False, server_default=""),
        sa.Column("agent_api_key", sa.Text(), nullable=False, server_default=""),
        sa.Column("agent_model", sa.String(160), nullable=False, server_default=""),
        sa.Column("agent_thinking_mode", sa.String(16), nullable=False, server_default=""),
        sa.Column("agent_timeout_seconds", sa.Float(), nullable=False, server_default="20"),
        sa.Column("mineru_provider", sa.String(16), nullable=False, server_default="local"),
        sa.Column(
            "mineru_local_url",
            sa.String(500),
            nullable=False,
            server_default="http://127.0.0.1:8001",
        ),
        sa.Column("mineru_backend", sa.String(64), nullable=False, server_default="pipeline"),
        sa.Column("mineru_language", sa.String(32), nullable=False, server_default="ch"),
        sa.Column("mineru_parse_method", sa.String(32), nullable=False, server_default="auto"),
        sa.Column(
            "mineru_official_api_url",
            sa.String(500),
            nullable=False,
            server_default="https://mineru.net/api/v4",
        ),
        sa.Column("mineru_official_api_token", sa.Text(), nullable=False, server_default=""),
        sa.Column("mineru_official_api_model", sa.String(64), nullable=False, server_default="vlm"),
        sa.Column("mineru_ocr", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("mineru_formula_enable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("mineru_table_enable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "mineru_request_timeout_seconds",
            sa.Float(),
            nullable=False,
            server_default="60",
        ),
        sa.Column("mineru_request_retries", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("mineru_task_timeout_seconds", sa.Float(), nullable=False, server_default="600"),
        sa.Column("mineru_poll_interval_seconds", sa.Float(), nullable=False, server_default="2"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("integration_config")
