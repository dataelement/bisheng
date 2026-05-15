"""F036: allow Shougang portal knowledge-space file share links.

Revision ID: f036_share_link_knowledge_space_file
Revises: f035_user_tenant_subtree_cleanup
Create Date: 2026-05-15
"""
from typing import Sequence, Union
import re

from alembic import op

revision: str = 'f036_share_link_knowledge_space_file'
down_revision: Union[str, Sequence[str], None] = 'f035_user_tenant_subtree_cleanup'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.execute("ALTER TYPE resourcetypeenum ADD VALUE IF NOT EXISTS 'KNOWLEDGE_SPACE_FILE'")
        return
    if bind.dialect.name == 'mysql':
        row = bind.exec_driver_sql("SHOW COLUMNS FROM share_link LIKE 'resource_type'").first()
        if not row:
            return
        column_type = str(row[1])
        enum_values = re.findall(r"'((?:[^']|'')*)'", column_type)
        if 'KNOWLEDGE_SPACE_FILE' in enum_values:
            return
        enum_values.append('KNOWLEDGE_SPACE_FILE')
        escaped = ','.join(f"'{value.replace(chr(39), chr(39) * 2)}'" for value in enum_values)
        nullable = 'NULL' if str(row[2]).upper() == 'YES' else 'NOT NULL'
        default_value = row[4]
        default_sql = ''
        if default_value is not None:
            default_sql = f" DEFAULT '{str(default_value).replace(chr(39), chr(39) * 2)}'"
        op.execute(
            f"ALTER TABLE share_link "
            f"MODIFY COLUMN resource_type ENUM({escaped}) {nullable}{default_sql}"
        )


def downgrade() -> None:
    # 如果已经创建 knowledge_space_file 分享记录，直接收窄 ENUM 会失败。
    # 这里保持 no-op，避免回滚时破坏已有分享数据。
    return
