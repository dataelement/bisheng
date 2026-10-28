"""异常上传列表按租户、状态、删除标记查询. 不新增列."""

from alembic import op

from bisheng.core.database.dialect_helpers import index_exists, table_exists

revision = "f119_abnormal_upload_status_index"
down_revision = "f118_file_belonging_organization"
branch_labels = None
depends_on = None

_TABLE = "knowledgefile"
_INDEX = "idx_kfile_tenant_status_deleted"


def upgrade() -> None:
    connection = op.get_bind()
    if table_exists(connection, _TABLE) and not index_exists(connection, _TABLE, _INDEX):
        op.create_index(_INDEX, _TABLE, ["tenant_id", "status", "deleted_at"])


def downgrade() -> None:
    connection = op.get_bind()
    if table_exists(connection, _TABLE) and index_exists(connection, _TABLE, _INDEX):
        op.drop_index(_INDEX, table_name=_TABLE)
