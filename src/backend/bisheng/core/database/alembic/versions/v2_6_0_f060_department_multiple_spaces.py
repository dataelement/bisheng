"""F060: allow one department to bind multiple knowledge spaces.

Revision ID: f060_department_multiple_spaces
Revises: current repository heads on 2026-07-16
Create Date: 2026-07-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import (
    constraint_exists,
    index_exists,
    table_exists,
)

revision: str = "f060_department_multiple_spaces"
down_revision: str | Sequence[str] | None = (
    "f044_route_allowlist",
    "v2_5_0_sg_048_portal_hot_search",
    "v2_5_0_sg_f059_knowledge_sort_weight",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "department_knowledge_space"
_DEPARTMENT_UNIQUE = "uk_dks_department_id"
_DEPARTMENT_INDEX = "idx_dks_department_id"
_SPACE_UNIQUE = "uk_dks_space_id"


def upgrade() -> None:
    connection = op.get_bind()
    if not table_exists(connection, _TABLE):
        return

    if constraint_exists(connection, _TABLE, _DEPARTMENT_UNIQUE):
        op.drop_constraint(_DEPARTMENT_UNIQUE, _TABLE, type_="unique")
    elif index_exists(connection, _TABLE, _DEPARTMENT_UNIQUE):
        op.drop_index(_DEPARTMENT_UNIQUE, table_name=_TABLE)

    if not index_exists(connection, _TABLE, _DEPARTMENT_INDEX):
        op.create_index(_DEPARTMENT_INDEX, _TABLE, ["department_id"])


def downgrade() -> None:
    connection = op.get_bind()
    if not table_exists(connection, _TABLE):
        return
    if constraint_exists(connection, _TABLE, _DEPARTMENT_UNIQUE) or index_exists(
        connection,
        _TABLE,
        _DEPARTMENT_UNIQUE,
    ):
        return

    binding = sa.table(
        _TABLE,
        sa.column("department_id", sa.Integer()),
    )
    duplicate = connection.execute(
        sa.select(binding.c.department_id).group_by(binding.c.department_id).having(sa.func.count() > 1)
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "department_knowledge_space contains duplicate department_id rows; "
            "resolve multiple bindings before restoring uk_dks_department_id"
        )

    op.create_unique_constraint(
        _DEPARTMENT_UNIQUE,
        _TABLE,
        ["department_id"],
    )
