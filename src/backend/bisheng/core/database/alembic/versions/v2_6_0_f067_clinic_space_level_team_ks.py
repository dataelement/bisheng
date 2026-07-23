"""Store clinic knowledge spaces as level 'team_ks'.

Revision ID: f067_clinic_space_level_team_ks
Revises: f066_token_file_sync_rule
Create Date: 2026-07-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f067_clinic_space_level_team_ks"
down_revision: str | Sequence[str] | None = "f066_token_file_sync_rule"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCOPE_TABLE = "knowledge_space_scope"
_BINDING_TABLE = "department_knowledge_space"


def _build_scope_table() -> sa.Table:
    return sa.table(
        _SCOPE_TABLE,
        sa.column("space_id", sa.Integer()),
        sa.column("level", sa.String(32)),
    )


def _build_binding_table() -> sa.Table:
    return sa.table(
        _BINDING_TABLE,
        sa.column("space_id", sa.Integer()),
    )


def upgrade() -> None:
    """Move existing clinic spaces from 'team' to 'team_ks'.

    Clinic spaces are identified by the presence of a row in
    department_knowledge_space. After this migration the application code
    stores new clinic spaces as 'team_ks' directly.
    """
    connection = op.get_bind()
    scope = _build_scope_table()
    binding = _build_binding_table()
    bound_space_ids = sa.select(binding.c.space_id)
    connection.execute(
        sa.update(scope)
        .where(scope.c.level == "team")
        .where(scope.c.space_id.in_(bound_space_ids))
        .values(level="team_ks")
    )


def downgrade() -> None:
    """Revert clinic spaces from 'team_ks' back to 'team'."""
    connection = op.get_bind()
    scope = _build_scope_table()
    binding = _build_binding_table()
    bound_space_ids = sa.select(binding.c.space_id)
    connection.execute(
        sa.update(scope)
        .where(scope.c.level == "team_ks")
        .where(scope.c.space_id.in_(bound_space_ids))
        .values(level="team")
    )
