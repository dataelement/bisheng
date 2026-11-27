"""merge release and multimodal finetune heads

Revision ID: v310_f025_merge_release_heads
Revises: v310_f001_credit_billing_extension, v310b1_f025_multimodal_finetune, f005_linsight_skill_auto_enabled
Create Date: 2026-11-25 15:27:48.758592

"""

from collections.abc import Sequence
from typing import Union

# revision identifiers, used by Alembic.
revision: str = "v310_f025_merge_release_heads"
down_revision: Union[str, Sequence[str], None] = (
    "v310_f001_credit_billing_extension",
    "v310b1_f025_multimodal_finetune",
    "f005_linsight_skill_auto_enabled",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
