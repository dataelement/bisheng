"""F039: knowledge_document + knowledge_document_version tables; simhash & similar_status on knowledgefile.

Revision ID: f039_knowledge_document_tables
Revises: f038_knowledge_space_auto_tags
Create Date: 2026-05-20
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, table_exists

revision: str = 'f039_knowledge_document_tables'
down_revision: Union[str, Sequence[str], None] = 'f038_knowledge_space_auto_tags'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DOC_TABLE = 'knowledge_document'
_VER_TABLE = 'knowledge_document_version'
_FILE_TABLE = 'knowledgefile'


def upgrade() -> None:
    # 1) knowledge_document
    if not table_exists(_DOC_TABLE):
        op.create_table(
            _DOC_TABLE,
            sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
            sa.Column('knowledge_id', sa.Integer, nullable=False, comment='Owning knowledge space ID'),
            sa.Column('file_level_path', sa.String(length=512), nullable=True, comment="Parent folder path"),
            sa.Column('level', sa.Integer, nullable=True, server_default=sa.text('0'), comment='Folder depth'),
            sa.Column('primary_version_id', sa.Integer, nullable=True, comment='FK to knowledge_document_version.id of the primary version'),
            sa.Column('create_time', sa.DateTime, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.Column(
                'update_time', sa.DateTime, nullable=False,
                server_default=sa.text('CURRENT_TIMESTAMP'),
                onupdate=sa.text('CURRENT_TIMESTAMP'),
            ),
            mysql_charset='utf8mb4',
            mysql_collate='utf8mb4_unicode_ci',
        )
        op.create_index('ix_knowledge_document_knowledge_id', _DOC_TABLE, ['knowledge_id'])
        op.create_index('ix_knowledge_document_file_level_path', _DOC_TABLE, ['file_level_path'])

    # 2) knowledge_document_version
    if not table_exists(_VER_TABLE):
        op.create_table(
            _VER_TABLE,
            sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
            sa.Column('document_id', sa.Integer, nullable=False, comment='FK to knowledge_document.id'),
            sa.Column('knowledge_file_id', sa.Integer, nullable=False, comment='FK to knowledgefile.id'),
            sa.Column('version_no', sa.Integer, nullable=False, comment='Version number within document (V1=1, ...)'),
            sa.Column('is_primary', sa.Boolean(), nullable=False, server_default=sa.text('0')),
            sa.Column('create_time', sa.DateTime, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.Column(
                'update_time', sa.DateTime, nullable=False,
                server_default=sa.text('CURRENT_TIMESTAMP'),
                onupdate=sa.text('CURRENT_TIMESTAMP'),
            ),
            sa.UniqueConstraint('document_id', 'version_no', name='uk_kdv_document_version'),
            mysql_charset='utf8mb4',
            mysql_collate='utf8mb4_unicode_ci',
        )
        op.create_index('ix_knowledge_document_version_document_id', _VER_TABLE, ['document_id'])
        op.create_index('ix_knowledge_document_version_knowledge_file_id', _VER_TABLE, ['knowledge_file_id'])

    # 3) knowledgefile new columns
    if table_exists(_FILE_TABLE):
        if not column_exists(_FILE_TABLE, 'simhash'):
            op.add_column(
                _FILE_TABLE,
                sa.Column(
                    'simhash', sa.String(length=16), nullable=True,
                    comment='64-bit SimHash hex (16 chars)',
                ),
            )
        if not column_exists(_FILE_TABLE, 'similar_status'):
            op.add_column(
                _FILE_TABLE,
                sa.Column(
                    'similar_status', sa.Integer, nullable=False, server_default=sa.text('0'),
                    comment='0=no similar / 1=pending / 2=resolved',
                ),
            )


def downgrade() -> None:
    if table_exists(_FILE_TABLE):
        if column_exists(_FILE_TABLE, 'similar_status'):
            op.drop_column(_FILE_TABLE, 'similar_status')
        if column_exists(_FILE_TABLE, 'simhash'):
            op.drop_column(_FILE_TABLE, 'simhash')

    if table_exists(_VER_TABLE):
        op.drop_index('ix_knowledge_document_version_knowledge_file_id', table_name=_VER_TABLE)
        op.drop_index('ix_knowledge_document_version_document_id', table_name=_VER_TABLE)
        op.drop_table(_VER_TABLE)

    if table_exists(_DOC_TABLE):
        op.drop_index('ix_knowledge_document_file_level_path', table_name=_DOC_TABLE)
        op.drop_index('ix_knowledge_document_knowledge_id', table_name=_DOC_TABLE)
        op.drop_table(_DOC_TABLE)
