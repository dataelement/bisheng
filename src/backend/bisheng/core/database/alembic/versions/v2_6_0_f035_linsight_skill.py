"""F035: create linsight_skill table (tenant custom skill metadata).

Revision ID: f035_linsight_skill
Revises: f043_backfill_channel_membership_relation
Create Date: 2026-06-11
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import index_exists, table_exists

revision: str = "f035_linsight_skill"
down_revision: Union[str, Sequence[str], None] = "f043_backfill_channel_membership_relation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "linsight_skill"


def upgrade() -> None:
    conn = op.get_bind()
    if not table_exists(conn, _TABLE):
        op.create_table(
            _TABLE,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False, server_default=sa.text("1"), comment="Tenant ID"),
            sa.Column("name", sa.String(length=64), nullable=False, comment="Skill name"),
            sa.Column("description", sa.Text(), nullable=False, comment="Skill description"),
            sa.Column("enabled", sa.Integer(), nullable=False, server_default=sa.text("1"), comment="Enabled flag"),
            sa.Column(
                "source",
                sa.String(length=32),
                nullable=False,
                server_default=sa.text("'manual'"),
                comment="Skill origin",
            ),
            sa.Column(
                "object_path", sa.String(length=512), nullable=False, comment="SKILL.md relative path under SKILLS_ROOT"
            ),
            sa.Column("size", sa.Integer(), nullable=False, server_default=sa.text("0"), comment="File size in bytes"),
            sa.Column("created_by", sa.Integer(), nullable=True, comment="Creator user id"),
            sa.Column("create_time", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("update_time", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("tenant_id", "name", name="uq_linsight_skill_tenant_name"),
        )

    if not index_exists(conn, _TABLE, "idx_linsight_skill_tenant_id"):
        op.create_index("idx_linsight_skill_tenant_id", _TABLE, ["tenant_id"])


def downgrade() -> None:
    conn = op.get_bind()
    if index_exists(conn, _TABLE, "idx_linsight_skill_tenant_id"):
        op.drop_index("idx_linsight_skill_tenant_id", table_name=_TABLE)
    if table_exists(conn, _TABLE):
        op.drop_table(_TABLE)
