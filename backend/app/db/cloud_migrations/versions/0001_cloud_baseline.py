"""Cloud-only PostgreSQL baseline.

The cloud database is intentionally rebuildable. Local SQLite tables are not
part of this migration chain and are never created by the Cloud migrator.
"""

from alembic import op

from app.models.cloud_entities import CloudSQLModel

revision = "0001_cloud_baseline"
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    bind = op.get_bind()
    for table in CloudSQLModel.metadata.sorted_tables:
        table.create(bind, checkfirst=False)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(CloudSQLModel.metadata.sorted_tables):
        table.drop(bind, checkfirst=True)
