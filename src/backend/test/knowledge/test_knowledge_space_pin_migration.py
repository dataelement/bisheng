import importlib
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError

MIGRATION_MODULE = "bisheng.core.database.alembic.versions.v2_6_0_f057_knowledge_space_user_link_pin"


def _create_tables(conn):
    metadata = sa.MetaData()
    user_link = sa.Table(
        "user_link",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("type_detail", sa.String(255), nullable=False),
        sa.Column("create_time", sa.DateTime, nullable=False),
        sa.Column("update_time", sa.DateTime, nullable=False),
    )
    member = sa.Table(
        "space_channel_member",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("business_id", sa.String(36), nullable=False),
        sa.Column("business_type", sa.String(32), nullable=False),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("is_pinned", sa.Boolean, nullable=False),
    )
    scope = sa.Table(
        "knowledge_space_scope",
        metadata,
        sa.Column("space_id", sa.Integer, primary_key=True),
        sa.Column("level", sa.String(32), nullable=False),
    )
    metadata.create_all(conn)
    return user_link, member, scope


def test_deduplicate_keeps_newest_then_largest_id_and_preserves_other_groups():
    migration = importlib.import_module(MIGRATION_MODULE)
    engine = sa.create_engine("sqlite://")
    now = datetime(2026, 7, 14, 12, 0, 0)
    with engine.begin() as conn:
        user_link, _, _ = _create_tables(conn)
        conn.execute(
            sa.insert(user_link),
            [
                {"id": 1, "user_id": 7, "type": "x", "type_detail": "a", "create_time": now, "update_time": now},
                {
                    "id": 2,
                    "user_id": 7,
                    "type": "x",
                    "type_detail": "a",
                    "create_time": now + timedelta(seconds=1),
                    "update_time": now,
                },
                {
                    "id": 3,
                    "user_id": 7,
                    "type": "x",
                    "type_detail": "a",
                    "create_time": now + timedelta(seconds=1),
                    "update_time": now,
                },
                {"id": 4, "user_id": 7, "type": "x", "type_detail": "b", "create_time": now, "update_time": now},
                {"id": 5, "user_id": 8, "type": "x", "type_detail": "a", "create_time": now, "update_time": now},
            ],
        )

        migration._deduplicate(conn, migration._tables()[0])
        rows = conn.execute(sa.select(user_link.c.id).order_by(user_link.c.id)).scalars().all()

    assert rows == [3, 4, 5]


def test_backfill_only_active_nonpersonal_space_pins_and_is_idempotent():
    migration = importlib.import_module(MIGRATION_MODULE)
    engine = sa.create_engine("sqlite://")
    now = datetime(2026, 7, 14, 12, 0, 0)
    with engine.begin() as conn:
        user_link, member, scope = _create_tables(conn)
        conn.execute(
            sa.insert(scope),
            [
                {"space_id": 10, "level": "public"},
                {"space_id": 11, "level": "department"},
                {"space_id": 12, "level": "personal"},
            ],
        )
        conn.execute(
            sa.insert(member),
            [
                {
                    "id": 1,
                    "business_id": "10",
                    "business_type": "SPACE",
                    "user_id": 1,
                    "status": "ACTIVE",
                    "is_pinned": True,
                },
                {
                    "id": 2,
                    "business_id": "11",
                    "business_type": "SPACE",
                    "user_id": 1,
                    "status": "ACTIVE",
                    "is_pinned": True,
                },
                {
                    "id": 3,
                    "business_id": "12",
                    "business_type": "SPACE",
                    "user_id": 1,
                    "status": "ACTIVE",
                    "is_pinned": True,
                },
                {
                    "id": 4,
                    "business_id": "10",
                    "business_type": "CHANNEL",
                    "user_id": 2,
                    "status": "ACTIVE",
                    "is_pinned": True,
                },
                {
                    "id": 5,
                    "business_id": "11",
                    "business_type": "SPACE",
                    "user_id": 2,
                    "status": "PENDING",
                    "is_pinned": True,
                },
                {
                    "id": 6,
                    "business_id": "11",
                    "business_type": "SPACE",
                    "user_id": 3,
                    "status": "ACTIVE",
                    "is_pinned": False,
                },
            ],
        )
        conn.execute(
            sa.insert(user_link).values(
                user_id=1,
                type="knowledge_space_pin",
                type_detail="10",
                create_time=now,
                update_time=now,
            )
        )

        table_defs = migration._tables()
        migration._backfill(conn, *table_defs)
        migration._backfill(conn, *table_defs)

        pins = conn.execute(
            sa.select(user_link.c.user_id, user_link.c.type_detail)
            .where(user_link.c.type == "knowledge_space_pin")
            .order_by(user_link.c.type_detail)
        ).all()
        channel_pin = conn.execute(sa.select(member.c.is_pinned).where(member.c.id == 4)).scalar_one()

    assert pins == [(1, "10"), (1, "11")]
    assert channel_pin is True


def test_mysql_space_join_uses_business_id_collation():
    migration = importlib.import_module(MIGRATION_MODULE)
    _, member, scope = migration._tables()
    conn = SimpleNamespace(dialect=SimpleNamespace(name="mysql"))
    condition = migration._space_id_join_value(conn, scope) == member.c.business_id

    sql = str(condition.compile(dialect=mysql.dialect()))

    assert "COLLATE utf8mb4_unicode_ci" in sql


def test_orm_unique_constraint_rejects_duplicate_triple():
    from bisheng.database.models.user_link import UserLink

    engine = sa.create_engine("sqlite://")
    UserLink.__table__.create(engine)
    with engine.begin() as conn:
        conn.execute(sa.insert(UserLink).values(user_id=1, type="knowledge_space_pin", type_detail="10"))
        with pytest.raises(IntegrityError):
            conn.execute(sa.insert(UserLink).values(user_id=1, type="knowledge_space_pin", type_detail="10"))
