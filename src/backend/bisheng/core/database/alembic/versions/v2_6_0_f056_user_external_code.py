"""F056: add user.external_code for SG MDM / SSO matching.

Revision ID: f056_user_external_code
Revises: f055_message_citation_relation
Create Date: 2026-07-14

Adds ``user.external_code`` (VARCHAR(255) NULL).

ORM model: ``bisheng.user.domain.models.user.User.external_code``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists, table_exists

revision: str = "f056_user_external_code"
down_revision: Union[str, Sequence[str], None] = "f055_message_citation_relation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    if not table_exists(conn, "user"):
        return

    if not column_exists(conn, "user", "external_code"):
        op.add_column(
            "user",
            sa.Column(
                "external_code",
                sa.String(length=255),
                nullable=True,
                comment="External employee code for SG MDM / SSO matching",
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()
    if column_exists(conn, "user", "external_code"):
        op.drop_column("user", "external_code")
