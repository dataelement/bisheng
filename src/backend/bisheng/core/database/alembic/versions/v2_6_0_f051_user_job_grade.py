"""F049: add job_grade flag column to user.

The Gateway org sync (``/internal/sso/gateway-wecom-org-sync``) pushes the
upstream HR job grade as ``user_attrs.jobGrade``. It is a 0/1 flag: only an
explicit ``1`` is stored as 1; every other case is stored as 0. Persisted
on ``user.job_grade`` next to name/email/phone.

The pre-release shape of this revision was ``VARCHAR(64)``. Environments
that already ran that shape get the column dropped first and re-added as
INTEGER, so the type change completes inside this single revision.

Revision ID: f051_user_job_grade
Revises: f050_skill_frontend_hidden
Create Date: 2026-08-17
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, table_exists

revision: str = "f051_user_job_grade"
down_revision: Union[str, Sequence[str], None] = "f050_skill_frontend_hidden"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("user"):
        return
    # Drop the legacy VARCHAR shape from early builds of this revision, then
    # (re)create the 0/1 INTEGER flag with a server default of 0.
    if column_exists("user", "job_grade"):
        op.drop_column("user", "job_grade")
    op.add_column(
        "user",
        sa.Column(
            "job_grade",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="Job grade flag (0/1) synced from org sync payload jobGrade; 1 only when upstream sends 1",
        ),
    )


def downgrade() -> None:
    if not table_exists("user"):
        return
    if column_exists("user", "job_grade"):
        op.drop_column("user", "job_grade")
