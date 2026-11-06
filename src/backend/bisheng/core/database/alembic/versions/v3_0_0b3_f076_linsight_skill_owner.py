"""F076: personal skills share linsight_skill, distinguished by owner.

Adds ``owner_user_id`` (0 = tenant skill) and nullable ``last_import_id``.
Replaces ``uq_linsight_skill_tenant_name`` with
``(tenant_id, owner_user_id, name)`` and adds
``(tenant_id, owner_user_id, last_import_id)``.

Existing rows are tenant skills. ``server_default 0`` fills ``owner_user_id``;
``last_import_id`` stays NULL. The previous unique constraint already keeps
``(tenant_id, name)`` unique, so the new name constraint does not need a
data rewrite. Multiple NULL import ids must be allowed. This revision does
not move objects and does not rewrite rows.

Revision ID: f076_linsight_skill_owner
Revises: merge_release_information_heads
Create Date: 2026-10-19
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists, constraint_exists

revision: str = "f076_linsight_skill_owner"
down_revision: Union[str, Sequence[str], None] = "merge_release_information_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "linsight_skill"
_OWNER = "owner_user_id"
_IMPORT = "last_import_id"
_OLD_NAME = "uq_linsight_skill_tenant_name"
_NAME_UQ = "uq_linsight_skill_tenant_owner_name"
_IMPORT_UQ = "uq_linsight_skill_tenant_owner_import"


def _has_unique(conn, name: str) -> bool:
    # DM8 reflects identifiers in uppercase. Match both spellings.
    return constraint_exists(conn, _TABLE, name) or constraint_exists(conn, _TABLE, name.upper())


def _drop_unique(conn, name: str) -> None:
    if constraint_exists(conn, _TABLE, name):
        op.drop_constraint(name, _TABLE, type_="unique")
    elif constraint_exists(conn, _TABLE, name.upper()):
        op.drop_constraint(name.upper(), _TABLE, type_="unique")


def upgrade() -> None:
    conn = op.get_bind()
    if not column_exists(conn, _TABLE, _OWNER):
        op.add_column(
            _TABLE,
            sa.Column(
                _OWNER,
                sa.Integer,
                nullable=False,
                server_default=sa.text("0"),
                comment="0 for a tenant skill; otherwise the owning user id",
            ),
        )
    if not column_exists(conn, _TABLE, _IMPORT):
        op.add_column(
            _TABLE,
            sa.Column(_IMPORT, sa.String(64), nullable=True, comment="Latest personal-skill import id"),
        )
    if not _has_unique(conn, _NAME_UQ):
        op.create_unique_constraint(_NAME_UQ, _TABLE, ["tenant_id", _OWNER, "name"])
    _drop_unique(conn, _OLD_NAME)
    if not _has_unique(conn, _IMPORT_UQ):
        # NULL import ids must not block each other. MySQL unique indexes
        # already treat NULL as distinct. If DM8 rejects a second NULL here,
        # stop and do not replace this constraint with another shape.
        op.create_unique_constraint(_IMPORT_UQ, _TABLE, ["tenant_id", _OWNER, _IMPORT])


def downgrade() -> None:
    conn = op.get_bind()
    _drop_unique(conn, _IMPORT_UQ)
    _drop_unique(conn, _NAME_UQ)
    if not _has_unique(conn, _OLD_NAME):
        op.create_unique_constraint(_OLD_NAME, _TABLE, ["tenant_id", "name"])
    if column_exists(conn, _TABLE, _IMPORT):
        op.drop_column(_TABLE, _IMPORT)
    if column_exists(conn, _TABLE, _OWNER):
        op.drop_column(_TABLE, _OWNER)
