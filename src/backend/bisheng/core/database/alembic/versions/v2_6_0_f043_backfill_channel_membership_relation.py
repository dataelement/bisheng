"""F043: backfill channel membership relation from legacy roles.

Revision ID: f043_backfill_channel_membership_relation
Revises: f042_channel_membership_relation_source
Create Date: 2026-05-28
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists

revision: str = 'f043_backfill_channel_membership_relation'
down_revision: Union[str, Sequence[str], None] = 'f042_channel_membership_relation_source'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    if not column_exists(conn, 'space_channel_member', 'relation'):
        return

    conn.execute(
        sa.text(
            """
            UPDATE space_channel_member
            SET relation = CASE user_role
                WHEN 'creator' THEN 'owner'
                WHEN 'admin' THEN 'manager'
                ELSE 'viewer'
            END,
            grant_subject_type = COALESCE(grant_subject_type, 'self'),
            grant_subject_id = COALESCE(grant_subject_id, user_id),
            grant_relation = CASE user_role
                WHEN 'creator' THEN 'owner'
                WHEN 'admin' THEN 'manager'
                ELSE 'viewer'
            END
            WHERE business_type = 'channel'
              AND relation IS NULL
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    if column_exists(conn, 'space_channel_member', 'relation'):
        conn.execute(
            sa.text(
                """
                UPDATE space_channel_member
                SET relation = NULL,
                    grant_subject_type = NULL,
                    grant_subject_id = NULL,
                    grant_relation = NULL,
                    grant_include_children = 0,
                    grant_model_id = NULL,
                    grant_binding_key = NULL
                WHERE business_type = 'channel'
                """
            )
        )
