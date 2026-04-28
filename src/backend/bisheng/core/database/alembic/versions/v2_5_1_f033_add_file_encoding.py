"""Add file_encoding column to knowledge_file (shougang feature, F033)

Revision ID: f033_add_file_encoding
Revises: f032_workbench_subscription_web_menu_backfill
Create Date: 2026-04-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = 'f033_add_file_encoding'
down_revision = 'f032_workbench_subscription_web_menu_backfill'
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    return table in insp.get_table_names()


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    return column in {c['name'] for c in insp.get_columns(table)}


def upgrade() -> None:
    # Fresh DB: knowledge_file is created later by SQLModel.metadata.create_all()
    # at app startup, which already includes the file_encoding column from the
    # model definition. This migration only needs to add the column on existing
    # databases that were created before this revision.
    if not _table_exists('knowledgefile'):
        return
    if not _column_exists('knowledgefile', 'file_encoding'):
        op.add_column(
            'knowledgefile',
            sa.Column(
                'file_encoding',
                sa.String(length=64),
                nullable=True,
                comment='File encoding for shougang deployment, e.g. GF-ZD-SC-202604-00001 (F033)',
            ),
        )


def downgrade() -> None:
    if not _table_exists('knowledgefile'):
        return
    if _column_exists('knowledgefile', 'file_encoding'):
        op.drop_column('knowledgefile', 'file_encoding')
