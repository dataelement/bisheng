"""Add a metadata_fields field to the knowledge table.

Revision ID: 9ba42685e830
Revises: 
Create Date: 2025-11-11 16:00:42.582363

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '9ba42685e830'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('knowledge', sa.Column('metadata_fields', sa.JSON, nullable=True, comment='知识库的元数据字段配置'))

    # knowledgefile 表的extra_meta 改为 user_metadata 字段
    op.add_column('knowledgefile', sa.Column('user_metadata', sa.JSON, nullable=True, comment='用户自定义的元数据'))

    # 将原 extra_meta 字段的数据迁移到 user_metadata 字段
    op.execute('UPDATE knowledgefile SET user_metadata = extra_meta')

    op.drop_column('knowledgefile', 'extra_meta')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('knowledge', 'metadata_fields')

    # 恢复 knowledgefile 表的 extra_meta 字段
    op.add_column('knowledgefile',
                  sa.Column('extra_meta', sa.VARCHAR(255), nullable=True, comment='用户自定义的元数据'))
    op.execute('UPDATE knowledgefile SET extra_meta = user_metadata')
    op.drop_column('knowledgefile', 'user_metadata')
