"""F037: merge f036_tenant_workstation_config and f036_sensitive_word_policy heads.

Revision ID: f037_merge_f036_heads
Revises: f036_tenant_workstation_config, f036_sensitive_word_policy
Create Date: 2026-05-13
"""
from typing import Sequence, Union

revision: str = 'f037_merge_f036_heads'
down_revision: Union[str, Sequence[str], None] = (
    'f036_tenant_workstation_config',
    'f036_sensitive_word_policy',
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
