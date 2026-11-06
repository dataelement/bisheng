"""Merge the 3.0-vibe head with the feat/3.0.0-beta3 DSH / plugin-market head.

Revision ID: merge_vibe_beta3_dsh_market
Revises: merge_f055_hosted_app_chatmsg_index, f064_enterprise_market
Create Date: 2026-10-08

``merge_f055_hosted_app_chatmsg_index`` is the 3.0-vibe head (hosted apps);
``f064_enterprise_market`` (after ``f062_profile_version``) came from
feat/3.0.0-beta3. Merging beta3 into vibe left two heads; this no-op revision
rejoins them so deployments can keep using ``alembic upgrade head``.
"""

from collections.abc import Sequence
from typing import Union

revision: str = "merge_vibe_beta3_dsh_market"
down_revision: Union[str, Sequence[str], None] = (
    "merge_f055_hosted_app_chatmsg_index",
    "f064_enterprise_market",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
