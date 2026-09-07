"""Re-join the COFCO line with the F053 open-API line.

``f054_merge_cofco_909_heads`` collapsed the graph once, but the 3.0 line has
advanced since: F053 (open API auth & identity) landed
``f053_pat_tenant_setting`` on ``feat/3.0.0-beta1``, and merging that branch
into this one forked the graph again. This empty merge revision re-collapses it
to a single head — entrypoint.sh fails fast on multiple heads and refuses to
start the API.

Revision ID: f055_merge_cofco_909_f053_heads
Revises: f054_merge_cofco_909_heads, f053_pat_tenant_setting
Create Date: 2026-09-07
"""

from collections.abc import Sequence
from typing import Union

revision: str = "f055_merge_cofco_909_f053_heads"
down_revision: Union[str, Sequence[str], None] = (
    "f054_merge_cofco_909_heads",
    "f053_pat_tenant_setting",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No schema change: this revision only re-joins two migration lines."""


def downgrade() -> None:
    """No schema change to undo."""
