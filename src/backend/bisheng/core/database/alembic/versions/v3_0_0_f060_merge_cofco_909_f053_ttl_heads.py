"""Re-collapse the graph after the F053 personal-token TTL change landed upstream.

Same shape as f057 and f059 before it: the COFCO branch carries its own merge
revision, so every main-line revision pulled in afterwards opens a second head.
This one has no DDL; it only restores the single head `alembic upgrade head`
requires, which entrypoint.sh checks before it will start the API.

Revision ID: f060_merge_cofco_909_f053_ttl_heads
Revises: f059_merge_cofco_909_f058_heads, f053_pat_default_ttl_365
Create Date: 2026-09-11
"""

from collections.abc import Sequence
from typing import Union

revision: str = "f060_merge_cofco_909_f053_ttl_heads"
down_revision: Union[str, Sequence[str], None] = (
    "f059_merge_cofco_909_f058_heads",
    "f053_pat_default_ttl_365",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
