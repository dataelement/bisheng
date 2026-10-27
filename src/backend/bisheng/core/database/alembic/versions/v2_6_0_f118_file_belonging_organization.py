"""文件新增可空所属组织, 不回填历史数据。"""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists, table_exists

revision = "f118_file_belonging_organization"
down_revision = "f117_portal_course_duration_seconds"
branch_labels = None
depends_on = None

_TABLE = "knowledgefile"
_COLUMN = "belonging_organization_id"


def upgrade() -> None:
    connection = op.get_bind()
    if table_exists(connection, _TABLE) and not column_exists(connection, _TABLE, _COLUMN):
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.Integer(), nullable=True, comment="文件所属组织ID"))


def downgrade() -> None:
    connection = op.get_bind()
    if table_exists(connection, _TABLE) and column_exists(connection, _TABLE, _COLUMN):
        if connection.dialect.name == "sqlite":
            with op.batch_alter_table(_TABLE) as batch:
                batch.drop_column(_COLUMN)
        else:
            op.drop_column(_TABLE, _COLUMN)
