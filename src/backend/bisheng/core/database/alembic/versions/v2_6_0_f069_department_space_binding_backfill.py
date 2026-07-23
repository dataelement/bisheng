"""补齐部门级知识空间缺失的审批部门关系。

Revision ID: f069_department_space_binding_backfill
Revises: f068_department_file_view_scenario_seed
Create Date: 2026-07-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import table_exists

revision: str = "f069_department_space_binding_backfill"
down_revision: str | Sequence[str] | None = "f068_department_file_view_scenario_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REQUIRED_TABLES = (
    "knowledge_space_scope",
    "department",
    "department_knowledge_space",
)


def _tables():
    scope = sa.table(
        "knowledge_space_scope",
        sa.column("tenant_id", sa.Integer()),
        sa.column("space_id", sa.Integer()),
        sa.column("level", sa.String()),
        sa.column("owner_type", sa.String()),
        sa.column("owner_id", sa.Integer()),
        sa.column("created_by", sa.Integer()),
    )
    department = sa.table(
        "department",
        sa.column("id", sa.Integer()),
        sa.column("tenant_id", sa.Integer()),
        sa.column("status", sa.String()),
        sa.column("is_deleted", sa.Integer()),
    )
    binding = sa.table(
        "department_knowledge_space",
        sa.column("tenant_id", sa.Integer()),
        sa.column("department_id", sa.Integer()),
        sa.column("space_id", sa.Integer()),
        sa.column("created_by", sa.Integer()),
        sa.column("approval_enabled", sa.Boolean()),
        sa.column("sensitive_check_enabled", sa.Boolean()),
    )
    return scope, department, binding


def _backfill(connection) -> None:
    scope, department, binding = _tables()
    missing_bindings = (
        sa.select(
            scope.c.tenant_id,
            scope.c.owner_id,
            scope.c.space_id,
            scope.c.created_by,
            sa.literal(True),
            sa.literal(False),
        )
        .select_from(
            scope.join(
                department,
                sa.and_(
                    department.c.id == scope.c.owner_id,
                    department.c.tenant_id == scope.c.tenant_id,
                ),
            ).outerjoin(
                binding,
                binding.c.space_id == scope.c.space_id,
            )
        )
        .where(
            scope.c.level == "department",
            scope.c.owner_type == "department",
            department.c.status == "active",
            department.c.is_deleted == 0,
            binding.c.space_id.is_(None),
        )
    )
    connection.execute(
        sa.insert(binding).from_select(
            [
                "tenant_id",
                "department_id",
                "space_id",
                "created_by",
                "approval_enabled",
                "sensitive_check_enabled",
            ],
            missing_bindings,
        )
    )


def upgrade() -> None:
    connection = op.get_bind()
    if not all(table_exists(connection, table_name) for table_name in _REQUIRED_TABLES):
        return
    _backfill(connection)


def downgrade() -> None:
    # 无可靠标记可区分回填关系与升级后已被业务继续使用的关系。
    # 自动删除会重新制造 scope/binding 不一致。因此降级只回退版本号。
    pass
