"""merge main work110 and release 3.0.0 heads

Revision ID: merge_main_work110_release300
Revises: asr_rt_model_type, merge_skill_center_heads, work110_dsh_local_sessions
Create Date: 2026-10-23 17:34:05.562304

"""

from collections.abc import Sequence
from typing import Union

# revision identifiers, used by Alembic.
revision: str = "merge_main_work110_release300"
down_revision: Union[str, Sequence[str], None] = (
    "asr_rt_model_type",
    "merge_skill_center_heads",
    "work110_dsh_local_sessions",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
