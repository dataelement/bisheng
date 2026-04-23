"""F026: make role-name uniqueness respect department scope.

Revision ID: f026_role_scope_name_unique
Revises: f025_merge_f024_heads
Create Date: 2026-04-23

Changes:
  - DROP UNIQUE uk_tenant_roletype_rolename
  - CREATE UNIQUE uk_tenant_roletype_rolename_scope
    ON role(tenant_id, role_type, role_name, department_id)

Notes:
  - Application-layer duplicate checks still enforce strict uniqueness for
    ``department_id IS NULL`` rows because MySQL UNIQUE allows multiple NULLs.
  - This migration primarily removes the false collision between roles that
    share a name but live under different department scopes.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f026_role_scope_name_unique'
down_revision: Union[str, Sequence[str], None] = 'f025_merge_f024_heads'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _constraint_exists(table_name: str, constraint_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND CONSTRAINT_NAME = :c"
    ), {'t': table_name, 'c': constraint_name})
    return result.scalar() > 0


def upgrade() -> None:
    if _constraint_exists('role', 'uk_tenant_roletype_rolename'):
        op.drop_constraint('uk_tenant_roletype_rolename', 'role', type_='unique')
    if not _constraint_exists('role', 'uk_tenant_roletype_rolename_scope'):
        op.create_unique_constraint(
            'uk_tenant_roletype_rolename_scope',
            'role',
            ['tenant_id', 'role_type', 'role_name', 'department_id'],
        )


def downgrade() -> None:
    if _constraint_exists('role', 'uk_tenant_roletype_rolename_scope'):
        op.drop_constraint('uk_tenant_roletype_rolename_scope', 'role', type_='unique')
    if not _constraint_exists('role', 'uk_tenant_roletype_rolename'):
        op.create_unique_constraint(
            'uk_tenant_roletype_rolename',
            'role',
            ['tenant_id', 'role_type', 'role_name'],
        )
