"""Re-collapse the graph after the F066 personal-token data scope landed upstream.

Same shape as f057, f059 and f060 before it: the COFCO branch carries its own
merge revision, so every main-line revision pulled in afterwards opens a second
head. This one has no DDL; it only restores the single head
`alembic upgrade head` requires, which entrypoint.sh checks before it will
start the API.

Revision ID: f061_merge_cofco_909_f066_heads
Revises: f060_merge_cofco_909_f053_ttl_heads, f066_pat_data_scope
Create Date: 2026-09-13
"""

from collections.abc import Sequence
from typing import Union

revision: str = "f061_merge_cofco_909_f066_heads"
down_revision: Union[str, Sequence[str], None] = (
    "f060_merge_cofco_909_f053_ttl_heads",
    "f066_pat_data_scope",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
