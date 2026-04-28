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


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    return column in {c['name'] for c in insp.get_columns(table)}


def upgrade() -> None:
    if not _column_exists('knowledge_file', 'file_encoding'):
        op.add_column(
            'knowledge_file',
            sa.Column(
                'file_encoding',
                sa.String(length=64),
                nullable=True,
                comment='File encoding for shougang deployment, e.g. GF-ZD-SC-202604-00001 (F033)',
            ),
        )


def downgrade() -> None:
    if _column_exists('knowledge_file', 'file_encoding'):
        op.drop_column('knowledge_file', 'file_encoding')
