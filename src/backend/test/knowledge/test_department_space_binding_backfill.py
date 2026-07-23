from unittest.mock import patch

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from bisheng.core.database.alembic.versions import (
    v2_6_0_f069_department_space_binding_backfill as migration,
)


def _create_tables(connection) -> tuple[sa.Table, sa.Table, sa.Table]:
    metadata = sa.MetaData()
    scope = sa.Table(
        "knowledge_space_scope",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("space_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("level", sa.String(32), nullable=False),
        sa.Column("owner_type", sa.String(64), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
    )
    department = sa.Table(
        "department",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("is_deleted", sa.Integer(), nullable=False),
    )
    binding = sa.Table(
        "department_knowledge_space",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("department_id", sa.Integer(), nullable=False),
        sa.Column("space_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("approval_enabled", sa.Boolean(), nullable=False),
        sa.Column("sensitive_check_enabled", sa.Boolean(), nullable=False),
    )
    metadata.create_all(connection)
    return scope, department, binding


def test_f069_backfills_only_valid_department_scopes_idempotently() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        scope, department, binding = _create_tables(connection)
        connection.execute(
            department.insert(),
            [
                {"id": 10, "tenant_id": 1, "status": "active", "is_deleted": 0},
                {"id": 11, "tenant_id": 1, "status": "archived", "is_deleted": 0},
                {"id": 12, "tenant_id": 1, "status": "active", "is_deleted": 1},
                {"id": 13, "tenant_id": 2, "status": "active", "is_deleted": 0},
            ],
        )
        connection.execute(
            scope.insert(),
            [
                {
                    "id": 1,
                    "tenant_id": 1,
                    "space_id": 101,
                    "level": "department",
                    "owner_type": "department",
                    "owner_id": 10,
                    "created_by": 7,
                },
                {
                    "id": 2,
                    "tenant_id": 1,
                    "space_id": 102,
                    "level": "department",
                    "owner_type": "department",
                    "owner_id": 10,
                    "created_by": 7,
                },
                {
                    "id": 3,
                    "tenant_id": 1,
                    "space_id": 103,
                    "level": "team",
                    "owner_type": "user",
                    "owner_id": 7,
                    "created_by": 7,
                },
                {
                    "id": 4,
                    "tenant_id": 1,
                    "space_id": 104,
                    "level": "team_ks",
                    "owner_type": "user",
                    "owner_id": 7,
                    "created_by": 7,
                },
                {
                    "id": 5,
                    "tenant_id": 1,
                    "space_id": 105,
                    "level": "department",
                    "owner_type": "department",
                    "owner_id": 11,
                    "created_by": 7,
                },
                {
                    "id": 6,
                    "tenant_id": 1,
                    "space_id": 106,
                    "level": "department",
                    "owner_type": "department",
                    "owner_id": 12,
                    "created_by": 7,
                },
                {
                    "id": 7,
                    "tenant_id": 1,
                    "space_id": 107,
                    "level": "department",
                    "owner_type": "department",
                    "owner_id": 13,
                    "created_by": 7,
                },
                {
                    "id": 8,
                    "tenant_id": 1,
                    "space_id": 108,
                    "level": "department",
                    "owner_type": "user",
                    "owner_id": 10,
                    "created_by": 7,
                },
            ],
        )
        connection.execute(
            binding.insert().values(
                tenant_id=1,
                department_id=10,
                space_id=102,
                created_by=8,
                approval_enabled=False,
                sensitive_check_enabled=True,
            )
        )

        operations = Operations(MigrationContext.configure(connection))
        with patch.object(migration, "op", operations):
            migration.upgrade()
            migration.upgrade()
            migration.downgrade()

        rows = connection.execute(
            sa.select(
                binding.c.space_id,
                binding.c.department_id,
                binding.c.created_by,
                binding.c.approval_enabled,
                binding.c.sensitive_check_enabled,
            ).order_by(binding.c.space_id)
        ).all()

    assert rows == [
        (101, 10, 7, True, False),
        (102, 10, 8, False, True),
    ]
    assert migration.revision == "f069_department_space_binding_backfill"
    assert migration.down_revision == "f068_department_file_view_scenario_seed"
