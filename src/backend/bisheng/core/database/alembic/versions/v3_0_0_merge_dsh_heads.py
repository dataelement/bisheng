"""Re-collapse the graph after the DSH line joined the unified 3.0.0.

Same shape as merge_beta1_beta2_heads: the DSH line kept its own revisions, so
merging it opens a second head. This one has no DDL; it only restores the
single head `alembic upgrade head` requires, which entrypoint.sh checks before
it will start the API.

Revision ID: merge_dsh_heads
Revises: merge_beta1_beta2_heads, f064_enterprise_market
Create Date: 2026-09-21
"""

from collections.abc import Sequence
from typing import Union

revision: str = "merge_dsh_heads"
down_revision: Union[str, Sequence[str], None] = (
    "merge_beta1_beta2_heads",
    "f064_enterprise_market",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
