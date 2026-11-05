"""Join the current 130 release schema with refresh-token recovery.

Keep both existing revision histories intact so databases upgraded on either
line can converge through the normal ``alembic upgrade head`` entry point.
"""

from collections.abc import Sequence

revision: str = "merge_f114_dsh_refresh"
down_revision: Sequence[str] = (
    "f114_app_authorization",
    "merge_work110_refresh_used_at_heads",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
