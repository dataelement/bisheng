"""Add portal course catalog and attach courses to a catalog.

Revision ID: f102_portal_course_catalog
Revises: f101_tag_blacklist
Create Date: 2026-08-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import (
    UPDATE_TIME_SERVER_DEFAULT,
    column_exists,
    index_exists,
    table_exists,
)

revision: str = "f102_portal_course_catalog"
down_revision: str | Sequence[str] | None = "f101_tag_blacklist"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CATALOG_TABLE = "portal_course_catalog"
_COURSE_TABLE = "portal_course"
_CATALOG_ID_COLUMN = "catalog_id"
_COURSE_CATALOG_INDEX = "ix_portal_course_tenant_catalog"


def upgrade() -> None:
    connection = op.get_bind()

    if not table_exists(connection, _CATALOG_TABLE):
        op.create_table(
            _CATALOG_TABLE,
            sa.Column("id", sa.CHAR(32), primary_key=True, nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column(
                "description",
                sa.String(200),
                nullable=False,
                server_default=sa.text("''"),
            ),
            sa.Column("parent_id", sa.CHAR(32), nullable=True),
            sa.Column("routing_path", sa.String(100), nullable=False),
            sa.Column("catalog_id_path", sa.String(1000), nullable=False),
            sa.Column("catalog_name_path", sa.String(1000), nullable=False),
            sa.Column(
                "order_index",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "deleted",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "opened",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("1"),
            ),
            sa.Column("create_user", sa.Integer(), nullable=False),
            sa.Column(
                "update_user",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "create_time",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "update_time",
                sa.DateTime(),
                nullable=False,
                server_default=UPDATE_TIME_SERVER_DEFAULT,
            ),
            sa.ForeignKeyConstraint(
                ["parent_id"],
                [f"{_CATALOG_TABLE}.id"],
                name="fk_portal_catalog_parent",
            ),
            mysql_charset="utf8mb4",
            mysql_collate="utf8mb4_unicode_ci",
        )
        op.create_index(
            "ix_portal_catalog_tenant_parent_order",
            _CATALOG_TABLE,
            ["tenant_id", "parent_id", "order_index"],
        )
        op.create_index(
            "ix_portal_catalog_tenant_deleted_opened",
            _CATALOG_TABLE,
            ["tenant_id", "deleted", "opened"],
        )
        op.create_index(
            "ix_portal_catalog_tenant_routing",
            _CATALOG_TABLE,
            ["tenant_id", "routing_path"],
        )

    if table_exists(connection, _COURSE_TABLE) and not column_exists(connection, _COURSE_TABLE, _CATALOG_ID_COLUMN):
        if connection.dialect.name == "sqlite":
            with op.batch_alter_table(_COURSE_TABLE) as batch_op:
                batch_op.add_column(sa.Column(_CATALOG_ID_COLUMN, sa.CHAR(32), nullable=True))
                batch_op.create_foreign_key(
                    "fk_portal_course_catalog",
                    _CATALOG_TABLE,
                    [_CATALOG_ID_COLUMN],
                    ["id"],
                )
        else:
            op.add_column(
                _COURSE_TABLE,
                sa.Column(_CATALOG_ID_COLUMN, sa.CHAR(32), nullable=True),
            )
            op.create_foreign_key(
                "fk_portal_course_catalog",
                _COURSE_TABLE,
                _CATALOG_TABLE,
                [_CATALOG_ID_COLUMN],
                ["id"],
            )

    if table_exists(connection, _COURSE_TABLE) and not index_exists(connection, _COURSE_TABLE, _COURSE_CATALOG_INDEX):
        op.create_index(
            _COURSE_CATALOG_INDEX,
            _COURSE_TABLE,
            ["tenant_id", _CATALOG_ID_COLUMN],
        )


def downgrade() -> None:
    connection = op.get_bind()
    if table_exists(connection, _COURSE_TABLE) and index_exists(connection, _COURSE_TABLE, _COURSE_CATALOG_INDEX):
        op.drop_index(_COURSE_CATALOG_INDEX, table_name=_COURSE_TABLE)
    if table_exists(connection, _COURSE_TABLE) and column_exists(connection, _COURSE_TABLE, _CATALOG_ID_COLUMN):
        if connection.dialect.name == "sqlite":
            with op.batch_alter_table(_COURSE_TABLE) as batch_op:
                batch_op.drop_column(_CATALOG_ID_COLUMN)
        else:
            op.drop_constraint("fk_portal_course_catalog", _COURSE_TABLE, type_="foreignkey")
            op.drop_column(_COURSE_TABLE, _CATALOG_ID_COLUMN)
    if table_exists(connection, _CATALOG_TABLE):
        op.drop_table(_CATALOG_TABLE)
