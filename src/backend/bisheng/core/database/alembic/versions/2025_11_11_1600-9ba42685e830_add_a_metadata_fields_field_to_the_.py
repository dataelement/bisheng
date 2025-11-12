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


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('knowledge', 'metadata_fields')
