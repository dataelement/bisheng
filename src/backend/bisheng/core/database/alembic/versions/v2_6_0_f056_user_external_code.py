"""F056: user.external_code — manual DDL already applied.

Revision ID: f056_user_external_code
Revises: f055_message_citation_relation
Create Date: 2026-07-14

Background:
  ``user.external_code`` (VARCHAR(255) NULL) and the backfill
  ``external_code = external_id`` were applied manually via SQL on target
  environments. This revision is a no-op marker so ``alembic upgrade head``
  can advance without re-running DDL or data updates.

  ORM model: ``bisheng.user.domain.models.user.User.external_code``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

revision: str = "f056_user_external_code"
down_revision: Union[str, Sequence[str], None] = "f055_message_citation_relation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Intentional no-op: column + backfill applied manually.
    pass


def downgrade() -> None:
    # Intentional no-op: do not drop a manually provisioned column.
    pass
