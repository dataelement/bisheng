"""Unify knowledge-space pin preferences in user_link.

Revision ID: f057_knowledge_space_user_link_pin
Revises: f056_user_external_code
Create Date: 2026-07-14
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import constraint_exists, index_exists, table_exists

revision: str = "f057_knowledge_space_user_link_pin"
down_revision: Union[str, Sequence[str], None] = "f056_user_external_code"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_USER_LINK = "user_link"
_MEMBER = "space_channel_member"
_SCOPE = "knowledge_space_scope"
_UNIQUE = "uk_user_link_user_type_detail"
_PIN_TYPE = "knowledge_space_pin"


def _tables():
    user_link = sa.table(
        _USER_LINK,
        sa.column("id", sa.Integer()),
        sa.column("user_id", sa.Integer()),
        sa.column("type", sa.String()),
        sa.column("type_detail", sa.String()),
        sa.column("create_time", sa.DateTime()),
        sa.column("update_time", sa.DateTime()),
    )
    member = sa.table(
        _MEMBER,
        sa.column("business_id", sa.String()),
        sa.column("business_type", sa.String()),
        sa.column("user_id", sa.Integer()),
        sa.column("status", sa.String()),
        sa.column("is_pinned", sa.Boolean()),
    )
    scope = sa.table(
        _SCOPE,
        sa.column("space_id", sa.Integer()),
        sa.column("level", sa.String()),
    )
    return user_link, member, scope


def _deduplicate(conn, user_link) -> None:
    rows = conn.execute(
        sa.select(
            user_link.c.id,
            user_link.c.user_id,
            user_link.c.type,
            user_link.c.type_detail,
            user_link.c.create_time,
        ).order_by(
            user_link.c.user_id,
            user_link.c.type,
            user_link.c.type_detail,
            user_link.c.create_time.is_(None),
            user_link.c.create_time.desc(),
            user_link.c.id.desc(),
        )
    ).all()
    seen: set[tuple[int, str, str]] = set()
    duplicate_ids: list[int] = []
    for row in rows:
        key = (int(row.user_id), str(row.type), str(row.type_detail))
        if key in seen:
            duplicate_ids.append(int(row.id))
        else:
            seen.add(key)
    for start in range(0, len(duplicate_ids), 500):
        conn.execute(sa.delete(user_link).where(user_link.c.id.in_(duplicate_ids[start : start + 500])))


def _backfill(conn, user_link, member, scope) -> None:
    existing = {
        (int(row.user_id), str(row.type_detail))
        for row in conn.execute(
            sa.select(user_link.c.user_id, user_link.c.type_detail).where(user_link.c.type == _PIN_TYPE)
        ).all()
    }
    rows = conn.execute(
        sa.select(member.c.user_id, member.c.business_id)
        .select_from(
            member.join(
                scope,
                sa.cast(scope.c.space_id, sa.String(36)) == member.c.business_id,
            )
        )
        .where(
            member.c.business_type == "SPACE",
            member.c.status == "ACTIVE",
            member.c.is_pinned.is_(True),
            scope.c.level != "personal",
        )
    ).all()
    for row in rows:
        key = (int(row.user_id), str(row.business_id))
        if key in existing:
            continue
        conn.execute(
            sa.insert(user_link).values(
                user_id=key[0],
                type=_PIN_TYPE,
                type_detail=key[1],
                create_time=sa.func.current_timestamp(),
                update_time=sa.func.current_timestamp(),
            )
        )
        existing.add(key)


def upgrade() -> None:
    conn = op.get_bind()
    if not table_exists(conn, _USER_LINK):
        return
    user_link, member, scope = _tables()
    _deduplicate(conn, user_link)
    if not constraint_exists(conn, _USER_LINK, _UNIQUE) and not index_exists(conn, _USER_LINK, _UNIQUE):
        op.create_unique_constraint(_UNIQUE, _USER_LINK, ["user_id", "type", "type_detail"])
    if table_exists(conn, _MEMBER) and table_exists(conn, _SCOPE):
        _backfill(conn, user_link, member, scope)


def downgrade() -> None:
    conn = op.get_bind()
    if table_exists(conn, _USER_LINK) and constraint_exists(conn, _USER_LINK, _UNIQUE):
        op.drop_constraint(_UNIQUE, _USER_LINK, type_="unique")
