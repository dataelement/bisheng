"""Re-collapse the release-line and Information article-sync migration heads.

Revision ID: merge_release_information_heads
Revises: merge_beta4_heads, f074_information_cursor_on_source
Create Date: 2026-10-14

The Information cursor migration branched from ``merge_enterprise_chat_heads``
while the release line advanced to ``merge_beta4_heads``. Preserve both published
histories and restore the single head required by API startup.
"""

from collections.abc import Sequence

revision: str = "merge_release_information_heads"
down_revision: str | Sequence[str] | None = (
    "merge_beta4_heads",
    "f074_information_cursor_on_source",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
