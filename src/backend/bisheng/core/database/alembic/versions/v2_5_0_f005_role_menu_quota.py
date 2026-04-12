"""F005: Extend role table with role_type, department_id, quota_config.

Revision ID: f005_role_menu_quota
Revises: f004_rebac
Create Date: 2026-04-12

Changes:
  - ADD COLUMN role_type VARCHAR(16) NOT NULL DEFAULT 'tenant'
  - ADD COLUMN department_id INT NULL (indexed)
  - ADD COLUMN quota_config JSON NULL
  - DROP INDEX group_role_name_uniq
  - CREATE UNIQUE INDEX uk_tenant_roletype_rolename ON role(tenant_id, role_type, role_name)
  - Backfill: AdminRole(1) and DefaultRole(2) set role_type='global'
  - Migrate: knowledge_space_file_limit > 0 values into quota_config
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f005_role_menu_quota'
down_revision: Union[str, Sequence[str], None] = 'f004_rebac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Extend role table for policy-role model (F005)."""
    # 1. Add role_type column
    op.add_column(
        'role',
        sa.Column('role_type', sa.String(16), nullable=False, server_default='tenant',
                  comment='global: cross-tenant visible; tenant: tenant-scoped'),
    )

    # 2. Add department_id column with index
    op.add_column(
        'role',
        sa.Column('department_id', sa.Integer, nullable=True,
                  comment='Department scope ID; NULL = no scope restriction'),
    )
    op.create_index('idx_role_department_id', 'role', ['department_id'])

    # 3. Add quota_config JSON column
    op.add_column(
        'role',
        sa.Column('quota_config', sa.JSON, nullable=True,
                  comment='Resource quota config JSON'),
    )

    # 4. Drop old unique constraint and create new one
    op.drop_index('group_role_name_uniq', table_name='role')
    op.create_unique_constraint(
        'uk_tenant_roletype_rolename', 'role',
        ['tenant_id', 'role_type', 'role_name'],
    )

    # 5. Backfill: set built-in roles to global
    op.execute("UPDATE role SET role_type = 'global' WHERE id IN (1, 2)")

    # 6. Migrate knowledge_space_file_limit into quota_config
    # Only for roles that have a positive limit set
    op.execute("""
        UPDATE role
        SET quota_config = JSON_OBJECT('knowledge_space_file', knowledge_space_file_limit)
        WHERE knowledge_space_file_limit > 0
          AND (quota_config IS NULL OR JSON_LENGTH(quota_config) = 0)
    """)


def downgrade() -> None:
    """Revert role table changes."""
    # Clear migrated quota_config values
    op.execute("""
        UPDATE role SET quota_config = NULL
        WHERE JSON_LENGTH(quota_config) = 1
          AND JSON_CONTAINS_PATH(quota_config, 'one', '$.knowledge_space_file')
    """)

    # Revert built-in roles
    op.execute("UPDATE role SET role_type = 'tenant' WHERE id IN (1, 2)")

    # Drop new unique constraint and restore old one
    op.drop_constraint('uk_tenant_roletype_rolename', 'role', type_='unique')
    op.create_unique_constraint('group_role_name_uniq', 'role', ['group_id', 'role_name'])

    # Drop new columns
    op.drop_column('role', 'quota_config')
    op.drop_index('idx_role_department_id', table_name='role')
    op.drop_column('role', 'department_id')
    op.drop_column('role', 'role_type')
