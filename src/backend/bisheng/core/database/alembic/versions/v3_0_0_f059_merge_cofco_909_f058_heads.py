"""Re-collapse the graph after f058 landed on the main line.

The COFCO branch carries its own merge revision (f057), so pulling the main
line's f058 in gives two heads. This merge has no DDL of its own; it only
restores the single head `alembic upgrade head` requires.

Revision ID: f059_merge_cofco_909_f058_heads
Revises: f057_merge_cofco_909_f056_heads, f058_widen_projection_idempotency_key
Create Date: 2026-09-09
"""

from collections.abc import Sequence
from typing import Union

revision: str = "f059_merge_cofco_909_f058_heads"
down_revision: Union[str, Sequence[str], None] = (
    "f057_merge_cofco_909_f056_heads",
    "f058_widen_projection_idempotency_key",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
