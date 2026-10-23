"""Merge the knowledge-file abnormal index and PAT data-scope heads.

Revision ID: merge_f064_f066_heads
Revises: f064_kb_file_abnormal_index, f066_pat_data_scope
Create Date: 2026-09-14

``f064_kb_file_abnormal_index`` landed on feat/3.0.0-beta2 and
``f066_pat_data_scope`` on feat/3.0.0-beta1; merging beta1 into beta2 left two
heads. This no-op revision rejoins both branches so deployments can keep using
``alembic upgrade head``.
"""

from collections.abc import Sequence
from typing import Union

revision: str = "merge_f064_f066_heads"
down_revision: Union[str, Sequence[str], None] = (
    "f064_kb_file_abnormal_index",
    "f066_pat_data_scope",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
