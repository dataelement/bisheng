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
    op.add_column('knowledge', sa.Column('metadata_fields', sa.JSON, nullable=True, comment='Metadata Field Configuration for Knowledge Base'))

    # knowledgefile OF TABLE)extra_meta to user_metadata Data field
    op.add_column('knowledgefile', sa.Column('user_metadata', sa.JSON, nullable=True, comment='User-defined metadata'))

    # Taking the original extra_meta Data migration of fields to user_metadata Data field
    op.execute('UPDATE knowledgefile SET user_metadata = extra_meta')

    op.drop_column('knowledgefile', 'extra_meta')

    op.add_column('knowledgefile',sa.Column('updater_id', sa.INT, nullable=True, comment='Updated ByID'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('knowledge', 'metadata_fields')

    # Recovery knowledgefile OF TABLE) extra_meta Data field
    op.add_column('knowledgefile',
                  sa.Column('extra_meta', sa.VARCHAR(255), nullable=True, comment='User-defined metadata'))
    op.execute('UPDATE knowledgefile SET extra_meta = user_metadata')
    op.drop_column('knowledgefile', 'user_metadata')

    op.drop_column('knowledgefile', 'updater_id')
