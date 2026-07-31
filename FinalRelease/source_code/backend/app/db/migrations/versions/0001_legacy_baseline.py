"""Iteration 1 legacy schema baseline."""

import sqlalchemy as sa
from alembic import op

revision = "0001_legacy_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_project_name", "project", ["name"])
    op.create_table(
        "paper_document",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("abstract", sa.Text(), nullable=False, server_default=""),
        sa.Column("sections_json", sa.JSON(), nullable=False),
        sa.Column("paragraphs_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_paper_document_project_id", "paper_document", ["project_id"])
    op.create_table(
        "code_repository",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("file_tree_json", sa.JSON(), nullable=False),
        sa.Column("symbols_json", sa.JSON(), nullable=False),
        sa.Column("imports_json", sa.JSON(), nullable=False),
        sa.Column("pytorch_candidates_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_code_repository_project_id", "code_repository", ["project_id"])
    op.create_table(
        "trace_link",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id"), nullable=False),
        sa.Column("paper_ref", sa.String(255), nullable=False),
        sa.Column("code_ref", sa.String(255), nullable=False),
        sa.Column("relation_type", sa.String(64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("rationale", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_trace_link_project_id", "trace_link", ["project_id"])


def downgrade() -> None:
    op.drop_table("trace_link")
    op.drop_table("code_repository")
    op.drop_table("paper_document")
    op.drop_table("project")
