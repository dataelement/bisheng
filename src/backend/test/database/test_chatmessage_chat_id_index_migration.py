"""The chatmessage.chat_id index migration only fills the gap it targets.

Runs the real ``upgrade()`` against an in-memory SQLite database through an
Alembic ``Operations`` context: a table without the index gets it; a table that
already leads an index with ``chat_id`` (under any name) is left alone.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

_MIGRATION = (
    Path(__file__).resolve().parents[2] / "bisheng/core/database/alembic/versions/v3_0_0b1_chatmessage_chat_id_index.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("chatmessage_chat_id_index", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _chat_id_indexes(conn):
    return [
        index["name"]
        for index in sa.inspect(conn).get_indexes("chatmessage")
        if (index.get("column_names") or [None])[0] == "chat_id"
    ]


@pytest.mark.parametrize(
    "existing_ddl,expected",
    [
        (None, ["ix_chatmessage_chat_id"]),
        ("CREATE INDEX ix_chatmessage_chat_id ON chatmessage (chat_id)", ["ix_chatmessage_chat_id"]),
        ("CREATE INDEX legacy_chat_id_idx ON chatmessage (chat_id, category)", ["legacy_chat_id_idx"]),
    ],
)
def test_upgrade_adds_the_index_only_when_no_index_leads_with_chat_id(monkeypatch, existing_ddl, expected):
    migration = _load()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE chatmessage (id INTEGER PRIMARY KEY, chat_id VARCHAR(64), category VARCHAR(32))"
        )
        conn.exec_driver_sql("CREATE INDEX ix_chatmessage_category ON chatmessage (category)")
        if existing_ddl:
            conn.exec_driver_sql(existing_ddl)
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            migration.upgrade()  # idempotent
        assert _chat_id_indexes(conn) == expected


def test_downgrade_keeps_the_model_index():
    migration = _load()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE chatmessage (id INTEGER PRIMARY KEY, chat_id VARCHAR(64))")
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            migration.downgrade()
        assert _chat_id_indexes(conn) == ["ix_chatmessage_chat_id"]
