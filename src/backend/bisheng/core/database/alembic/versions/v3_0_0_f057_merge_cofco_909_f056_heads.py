"""Re-join the COFCO line with the user-column-length change.

Third time on this branch, and for the same structural reason each time: the
mainline keeps adding revisions after whichever head the last merge collapsed.
Here it is F056 (bounded user string columns) landing on feat/3.0.0-beta1 while
this line sat at f055. See docs/cofco-merge-playbook.md §3.12 — check
`alembic heads` after every mainline merge, because entrypoint.sh refuses to
start on more than one and the failure only shows at deploy time.

Revision ID: f057_merge_cofco_909_f056_heads
Revises: f055_merge_cofco_909_f053_heads, f056_user_string_lengths
Create Date: 2026-09-08
"""

from collections.abc import Sequence
from typing import Union

revision: str = "f057_merge_cofco_909_f056_heads"
down_revision: Union[str, Sequence[str], None] = (
    "f055_merge_cofco_909_f053_heads",
    "f056_user_string_lengths",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No schema change: this revision only re-joins two migration lines."""


def downgrade() -> None:
    """No schema change to undo."""
