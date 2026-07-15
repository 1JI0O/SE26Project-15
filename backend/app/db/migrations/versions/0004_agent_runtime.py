"""Add persistent Agent conversations, runs, messages, and memory."""

import sqlalchemy as sa
from alembic import op

revision = "0004_agent_runtime"
down_revision = "0003_integration_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_conversation",
        sa.Column("conversation_id", sa.String(72), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id"), nullable=False),
        sa.Column("title", sa.String(160), nullable=False, server_default="新对话"),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_agent_conversation_project_id", "agent_conversation", ["project_id"])
    op.create_index("ix_agent_conversation_status", "agent_conversation", ["status"])
    op.create_index("ix_agent_conversation_updated_at", "agent_conversation", ["updated_at"])

    op.create_table(
        "agent_run",
        sa.Column("run_id", sa.String(72), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(72),
            sa.ForeignKey("agent_conversation.conversation_id"),
            nullable=False,
        ),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="running"),
        sa.Column("provider_name", sa.String(64), nullable=False, server_default=""),
        sa.Column("model_name", sa.String(160), nullable=False, server_default=""),
        sa.Column("step_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("trace_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("degraded_reason", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_agent_run_conversation_id", "agent_run", ["conversation_id"])
    op.create_index("ix_agent_run_project_id", "agent_run", ["project_id"])
    op.create_index("ix_agent_run_status", "agent_run", ["status"])

    op.create_table(
        "agent_message",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.String(72), nullable=False),
        sa.Column(
            "conversation_id",
            sa.String(72),
            sa.ForeignKey("agent_conversation.conversation_id"),
            nullable=False,
        ),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id"), nullable=False),
        sa.Column("role", sa.String(24), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("citations_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("message_id", name="uq_agent_message_id"),
    )
    op.create_index("ix_agent_message_message_id", "agent_message", ["message_id"])
    op.create_index("ix_agent_message_conversation_id", "agent_message", ["conversation_id"])
    op.create_index("ix_agent_message_project_id", "agent_message", ["project_id"])
    op.create_index("ix_agent_message_role", "agent_message", ["role"])
    op.create_index("ix_agent_message_created_at", "agent_message", ["created_at"])

    op.create_table(
        "agent_memory",
        sa.Column("memory_id", sa.String(72), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id"), nullable=True),
        sa.Column(
            "conversation_id",
            sa.String(72),
            sa.ForeignKey("agent_conversation.conversation_id"),
            nullable=True,
        ),
        sa.Column("scope", sa.String(24), nullable=False, server_default="project"),
        sa.Column("kind", sa.String(32), nullable=False, server_default="fact"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("importance", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("fingerprint", name="uq_agent_memory_fingerprint"),
    )
    op.create_index("ix_agent_memory_project_id", "agent_memory", ["project_id"])
    op.create_index("ix_agent_memory_conversation_id", "agent_memory", ["conversation_id"])
    op.create_index("ix_agent_memory_scope", "agent_memory", ["scope"])
    op.create_index("ix_agent_memory_kind", "agent_memory", ["kind"])
    op.create_index("ix_agent_memory_fingerprint", "agent_memory", ["fingerprint"])

    op.add_column("agent_tool_request", sa.Column("conversation_id", sa.String(72)))
    op.add_column("agent_tool_request", sa.Column("run_id", sa.String(72)))
    op.create_index(
        "ix_agent_tool_request_conversation_id",
        "agent_tool_request",
        ["conversation_id"],
    )
    op.create_index("ix_agent_tool_request_run_id", "agent_tool_request", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_tool_request_run_id", table_name="agent_tool_request")
    op.drop_index("ix_agent_tool_request_conversation_id", table_name="agent_tool_request")
    op.drop_column("agent_tool_request", "run_id")
    op.drop_column("agent_tool_request", "conversation_id")
    op.drop_table("agent_memory")
    op.drop_table("agent_message")
    op.drop_table("agent_run")
    op.drop_table("agent_conversation")
