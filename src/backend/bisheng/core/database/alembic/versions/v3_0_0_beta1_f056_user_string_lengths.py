"""F056: bound wide user string columns for stable DM8 sorting.

Unbounded SQLModel strings were created as ``VARCHAR2(8188)`` on DM8. Queries
that join ``user`` and ``userrole`` and sort by user name then allocate sort
rows for the declared maximum width, which can exhaust DM8 sort space under
concurrency even when the stored values are short.

Keep this revision DDL-only. Operators must verify that existing values fit
these limits before upgrading; an oversized value should make the migration
fail rather than be truncated.

Revision ID: f056_user_string_lengths
Revises: f053_pat_tenant_setting
Create Date: 2026-09-07
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists

revision: str = "f056_user_string_lengths"
down_revision: Union[str, Sequence[str], None] = "f053_pat_tenant_setting"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_USER_STRING_COLUMNS = (
    ("user_name", 128, False),
    ("email", 255, True),
    ("phone_number", 64, True),
    ("dept_id", 128, True),
    ("remark", 512, True),
    ("avatar", 512, True),
    ("password", 255, False),
)


def upgrade() -> None:
    for column_name, length, nullable in _USER_STRING_COLUMNS:
        if column_exists("user", column_name):
            op.alter_column(
                "user",
                column_name,
                existing_type=sa.String(),
                type_=sa.String(length=length),
                existing_nullable=nullable,
            )


def downgrade() -> None:
    # No-op: restoring dialect-specific unbounded VARCHAR columns would
    # re-introduce the DM8 sort-space failure this migration prevents.
    pass
