"""Merge the COFCO customization line into the 3.0 line.

The two advanced independently: the customization branch ended at
``f053_user_is_hidden`` (the hide-user flag), the 3.0 line at
``update_time_default_align``. This empty merge revision re-collapses the graph
to a single head so ``alembic upgrade head`` keeps working — entrypoint.sh
fails fast on multiple heads and refuses to start the API.

Revision ID: f054_merge_cofco_909_heads
Revises: f053_user_is_hidden, update_time_default_align
Create Date: 2026-09-01
"""

from collections.abc import Sequence
from typing import Union

revision: str = "f054_merge_cofco_909_heads"
down_revision: Union[str, Sequence[str], None] = ("f053_user_is_hidden", "update_time_default_align")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No schema change: this revision only re-joins two migration lines."""


def downgrade() -> None:
    """No schema change to undo."""
