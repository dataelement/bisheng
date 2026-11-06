"""Re-collapse the two heads on the feat/3.0.0 release line after the skill center.

Revision ID: merge_skill_center_heads
Revises: f077_subject_id_search_indexes, f076_session_skill_snapshot
Create Date: 2026-10-20

``f076_session_skill_snapshot`` (skill center, 2026-10-19) was chained onto
``f076_linsight_skill_owner`` while ``f077_subject_id_search_indexes`` had
already become the release line's head, so the line ended up with two heads
and ``alembic upgrade head`` refuses to run. This no-op revision restores the
single head.
"""

from collections.abc import Sequence
from typing import Union

revision: str = "merge_skill_center_heads"
down_revision: Union[str, Sequence[str], None] = (
    "f077_subject_id_search_indexes",
    "f076_session_skill_snapshot",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
