"""Merge the 0811 (file-change approval) and 0818 (cofco feature) migration lines.

Both branches advanced the schema independently — 0811 ended at
``f046_ks_file_change_approval``, 0818 at ``f051_user_job_grade``. This empty
merge revision re-collapses the graph to a single head so ``alembic upgrade
head`` keeps working (entrypoint.sh fails fast on multiple heads).

Revision ID: f052_merge_cofco_0811_heads
Revises: f046_ks_file_change_approval, f051_user_job_grade
Create Date: 2026-08-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f052_merge_cofco_0811_heads"
down_revision: Union[str, Sequence[str], None] = ("f046_ks_file_change_approval", "f051_user_job_grade")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
