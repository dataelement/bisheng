"""Rename ``user.job_grade`` to ``user.is_hidden``.

The flag's meaning was never "job grade": upstream sends ``user_attrs.jobGrade``
as a 0/1 marker for the handful of people who must not be offered in
grant-subject pickers. ``f051`` stored it under the upstream's name, which
reads as a job-grade code and misleads every later reader — the column is
renamed to say what it does. The wire field stays ``jobGrade``; only the
column and the Python attribute change.

Renaming rather than drop/add: the marked rows are a handful of real people,
and dropping the column would un-hide them until the next org sync ran.

Revision ID: f053_user_is_hidden
Revises: f052_merge_cofco_0811_heads
Create Date: 2026-08-28
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, table_exists

revision: str = "f053_user_is_hidden"
down_revision: Union[str, Sequence[str], None] = "f052_merge_cofco_0811_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COMMENT = "Hide this user from grant-subject pickers (0/1); set from org sync payload jobGrade"


def _copy(src: str, dst: str) -> None:
    """Carry the flag across, letting SQLAlchemy quote the reserved table name
    (``user``) for whichever dialect is running — MySQL and DM8 disagree."""
    table = sa.table("user", sa.column(src, sa.Integer), sa.column(dst, sa.Integer))
    op.execute(table.update().values({dst: table.c[src]}))


def upgrade() -> None:
    if not table_exists("user"):
        return
    if not column_exists("user", "is_hidden"):
        op.add_column(
            "user",
            sa.Column(
                "is_hidden",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
                comment=_COMMENT,
            ),
        )
        if column_exists("user", "job_grade"):
            _copy("job_grade", "is_hidden")
    if column_exists("user", "job_grade"):
        op.drop_column("user", "job_grade")


def downgrade() -> None:
    if not table_exists("user"):
        return
    if not column_exists("user", "job_grade"):
        op.add_column(
            "user",
            sa.Column(
                "job_grade",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
                comment="Job grade flag (0/1) synced from org sync payload jobGrade",
            ),
        )
        if column_exists("user", "is_hidden"):
            _copy("is_hidden", "job_grade")
    if column_exists("user", "is_hidden"):
        op.drop_column("user", "is_hidden")
