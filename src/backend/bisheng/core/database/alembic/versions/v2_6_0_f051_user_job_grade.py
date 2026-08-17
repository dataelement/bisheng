"""F049: add job_grade column to user.

The Gateway org sync (``/internal/sso/gateway-wecom-org-sync``) now pushes the
upstream HR job grade as ``user_attrs.jobGrade``; it is persisted on
``user.job_grade`` next to name/email/phone.

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
    if not column_exists("user", "job_grade"):
        op.add_column(
            "user",
            sa.Column(
                "job_grade",
                sa.String(length=64),
                nullable=True,
                comment="Job grade (职级) synced from org sync payload jobGrade",
            ),
        )


def downgrade() -> None:
    if not table_exists("user"):
        return
    if column_exists("user", "job_grade"):
        op.drop_column("user", "job_grade")
