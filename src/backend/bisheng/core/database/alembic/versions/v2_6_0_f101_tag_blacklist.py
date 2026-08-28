"""F101: tenant tag blacklist for rejected review tags.

Revision ID: f101_tag_blacklist
Revises: f100_migration_preserve_link
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, table_exists

revision: str = "f101_tag_blacklist"
down_revision: Union[str, Sequence[str], None] = "f100_migration_preserve_link"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "tag_blacklist"


def _create_table() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
            comment="Tenant ID",
        ),
        sa.Column("name", sa.String(length=255), nullable=False, comment="Blacklisted tag name"),
        sa.Column(
            "name_key",
            sa.String(length=255),
            nullable=False,
            comment="Normalized unique name key",
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="User who added the row",
        ),
        sa.Column(
            "create_time",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "update_time",
            sa.DateTime(),
            nullable=False,
            server_default=UPDATE_TIME_SERVER_DEFAULT,
        ),
        sa.UniqueConstraint("tenant_id", "name_key", name="uq_tag_blacklist_tenant_name_key"),
    )
    op.create_index("ix_tag_blacklist_tenant_id", _TABLE, ["tenant_id"])


def upgrade() -> None:
    conn = op.get_bind()
    if table_exists(conn, _TABLE):
        return
    _create_table()


def downgrade() -> None:
    conn = op.get_bind()
    if not table_exists(conn, _TABLE):
        return
    op.drop_index("ix_tag_blacklist_tenant_id", table_name=_TABLE)
    op.drop_table(_TABLE)
