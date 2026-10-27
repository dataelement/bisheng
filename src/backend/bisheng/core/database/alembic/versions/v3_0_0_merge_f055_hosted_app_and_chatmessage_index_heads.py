"""Merge the hosted-app credential and chatmessage.chat_id index heads.

Revision ID: merge_f055_hosted_app_chatmsg_index
Revises: f055_credential_hosted_app_subject, chatmessage_chat_id_index
Create Date: 2026-10-01

``f055_credential_hosted_app_subject`` exists only on 3.0-vibe (hosted apps);
``chatmessage_chat_id_index`` (after ``f073_linsight_api_meta``) came from
feat/3.0.0-beta2. Merging beta2 into vibe left two heads; this no-op revision
rejoins them so deployments can keep using ``alembic upgrade head``.
"""

from collections.abc import Sequence
from typing import Union

revision: str = "merge_f055_hosted_app_chatmsg_index"
down_revision: Union[str, Sequence[str], None] = (
    "f055_credential_hosted_app_subject",
    "chatmessage_chat_id_index",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
