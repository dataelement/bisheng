"""Widen QA multi-value asset fields for durable object references.

The wider column also keeps mixed-version compatibility with historical
presigned URLs while QA assets are migrated to permanent object keys.

Revision ID: f083_qa_answer_images_url_longtext
Revises: f082_department_short_name
Create Date: 2026-08-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import CLOB
from sqlalchemy.dialects import mysql

from bisheng.core.database.dialect_helpers import column_exists, get_column_type, table_exists

revision: str = "f083_qa_answer_images_url_longtext"
down_revision: str | Sequence[str] | None = "f082_department_short_name"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = (
    ("qa_question", "attachments"),
    ("qa_answer", "attachments"),
    ("qa_answer", "images_url"),
)
_VARCHAR_LENGTH = 255
_TARGET_TYPES = {"mysql": "longtext", "dm": "clob"}
_SUPPORTED_SOURCE_TYPES = {"varchar", "string", "text", "json"}


def _max_column_length(bind, table: str, column: str) -> int:
    result = bind.execute(sa.text(f"SELECT MAX(LENGTH({column})) FROM {table}"))
    value = result.scalar_one_or_none()
    return int(value or 0)


def _alter_to_large_text(dialect: str, table: str, column: str) -> None:
    if dialect == "mysql":
        op.alter_column(
            table,
            column,
            existing_type=mysql.VARCHAR(length=_VARCHAR_LENGTH),
            type_=mysql.LONGTEXT(),
            existing_nullable=True,
        )
    elif dialect == "dm":
        op.alter_column(
            table,
            column,
            existing_type=sa.VARCHAR(length=_VARCHAR_LENGTH),
            type_=CLOB(),
            existing_nullable=True,
        )


def _alter_to_varchar(dialect: str, table: str, column: str) -> None:
    if dialect == "mysql":
        op.alter_column(
            table,
            column,
            existing_type=mysql.LONGTEXT(),
            type_=mysql.VARCHAR(length=_VARCHAR_LENGTH),
            existing_nullable=True,
        )
    elif dialect == "dm":
        op.alter_column(
            table,
            column,
            existing_type=CLOB(),
            type_=sa.VARCHAR(length=_VARCHAR_LENGTH),
            existing_nullable=True,
        )


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    target_type = _TARGET_TYPES.get(dialect)
    if target_type is None:
        return

    upgrade_columns: list[tuple[str, str]] = []
    for table, column in _COLUMNS:
        if not table_exists(bind, table) or not column_exists(bind, table, column):
            continue
        current_type = get_column_type(bind, table, column)
        if current_type == target_type:
            continue
        if current_type not in _SUPPORTED_SOURCE_TYPES:
            raise RuntimeError(f"Unsupported {table}.{column} type for upgrade: {current_type}")
        upgrade_columns.append((table, column))

    for table, column in upgrade_columns:
        _alter_to_large_text(dialect, table, column)


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    target_type = _TARGET_TYPES.get(dialect)
    if target_type is None:
        return

    downgrade_columns: list[tuple[str, str]] = []
    for table, column in _COLUMNS:
        if not table_exists(bind, table) or not column_exists(bind, table, column):
            continue
        if get_column_type(bind, table, column) != target_type:
            continue
        max_length = _max_column_length(bind, table, column)
        if max_length > _VARCHAR_LENGTH:
            raise RuntimeError(
                f"Cannot downgrade {table}.{column} to VARCHAR({_VARCHAR_LENGTH}); "
                f"existing maximum length is {max_length}"
            )
        downgrade_columns.append((table, column))

    for table, column in reversed(downgrade_columns):
        _alter_to_varchar(dialect, table, column)
