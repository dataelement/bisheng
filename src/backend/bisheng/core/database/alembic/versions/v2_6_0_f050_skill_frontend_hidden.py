"""F047: frontend-hidden flag for tenant custom skills.

``linsight_skill.frontend_hidden``: hidden skills disappear from the
business-facing picker but, while enabled, are force-included into every task
run by the server. Hiding a skill auto-enables it in the same save; disabling
wins over hiding (a disabled skill is never dispatched).

DDL only; no data effect (default 0 = visible, current behavior).

Revision ID: f050_skill_frontend_hidden
Revises: f049_dks_admin_user_id
Create Date: 2026-08-17
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, table_exists

revision: str = "f050_skill_frontend_hidden"
down_revision: Union[str, Sequence[str], None] = "f049_dks_admin_user_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "linsight_skill"
_COLUMN = "frontend_hidden"


def upgrade() -> None:
    if not table_exists(_TABLE):
        # Fresh install: create_all() builds the table at its current model shape.
        return
    if not column_exists(_TABLE, _COLUMN):
        op.add_column(
            _TABLE,
            sa.Column(
                _COLUMN,
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
                comment="F047 frontend-hidden flag",
            ),
        )


def downgrade() -> None:
    if table_exists(_TABLE) and column_exists(_TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)
