"""F045: single space admin for department knowledge spaces.

Adds ``department_knowledge_space.admin_user_id`` — the one and only space
admin. NULL means the space is in the "pending admin configuration" state
(admin was deactivated / deleted / moved out of the tenant, or legacy data
could not be normalized to exactly one admin).

DDL only. Legacy normalization (adopting the single existing valid admin,
demoting auto-synced department admins, clearing the super-admin creator
footprint) is an out-of-band ops script: ``scripts/migrate_department_space_admin.py``.

Revision ID: f049_dks_admin_user_id
Revises: f048_merge_f046_f047_heads
Create Date: 2026-08-13
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, table_exists

revision: str = "f049_dks_admin_user_id"
down_revision: Union[str, Sequence[str], None] = "f048_merge_f046_f047_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "department_knowledge_space"
_COLUMN = "admin_user_id"
_INDEX = "ix_department_knowledge_space_admin_user_id"


def upgrade() -> None:
    if not table_exists(_TABLE):
        # Fresh install: create_all() already built the table at its current
        # SQLModel shape (column + index included).
        return
    if not column_exists(_TABLE, _COLUMN):
        op.add_column(
            _TABLE,
            sa.Column(
                _COLUMN,
                sa.Integer(),
                nullable=True,
                comment="F045: the single space admin; NULL means pending admin configuration",
            ),
        )
        op.create_index(_INDEX, _TABLE, [_COLUMN])


def downgrade() -> None:
    if table_exists(_TABLE) and column_exists(_TABLE, _COLUMN):
        op.drop_index(_INDEX, table_name=_TABLE)
        op.drop_column(_TABLE, _COLUMN)
