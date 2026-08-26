"""Guards for the IKB8XT fix: ``config.update_time`` must auto-advance.

The ``config`` table's ``update_time`` is read by F040 on every authorization
read (``ConfigDao.aget_config_version``) to key the process-local
relation-roster cache. If the DDL loses the ``ON UPDATE CURRENT_TIMESTAMP``
half — as SQLAlchemy's ``server_default=text("CURRENT_TIMESTAMP")``,
``onupdate=text("CURRENT_TIMESTAMP")`` model definition did — a freshly
saved ReBAC binding stays invisible to the reader for as long as the
process lives, and the user is left with the "knowledge-base page says
service exception" symptom reported in IKB8XT.

The model must now declare the dialect-aware marker
``UPDATE_TIME_SERVER_DEFAULT`` (which compiles to
``DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP`` on MySQL), and
the migration must repair existing upgrade-environment databases by
re-emitting the column with the missing ON UPDATE half. DaMeng gets
ON UPDATE from boot-time triggers and is a no-op; SQLite has no
equivalent clause.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy import Column, DateTime
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import (
    UPDATE_TIME_SERVER_DEFAULT,
    is_update_time_server_default,
)

# test/database/test_config_update_time_alignment.py -> parents[2] == src/backend
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION = (
    _BACKEND_ROOT
    / "bisheng"
    / "core"
    / "database"
    / "alembic"
    / "versions"
    / "v2_6_0_f049_config_update_time_on_update.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("f049_config_update_time_on_update", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, stmt, params=None):
        return SimpleNamespace(fetchall=lambda: self._rows)


class _FakeOp:
    def __init__(self, conn):
        self._conn = conn
        self.executed: list[str] = []

    def get_bind(self):
        return self._conn

    def execute(self, sql):
        self.executed.append(str(sql))


def _run_upgrade(monkeypatch, rows, *, dialect="mysql", declares_marker=True):
    module = _load_migration()
    op = _FakeOp(_FakeConn(rows))
    monkeypatch.setattr(module, "op", op)
    monkeypatch.setattr(module, "get_dialect_name", lambda _conn: dialect)
    monkeypatch.setattr(module, "_table_declares_the_marker", lambda: declares_marker)
    module.upgrade()
    return op.executed


class TestModelDeclaration:
    """The model side is the source of truth the migration aligns towards."""

    def test_config_update_time_uses_the_shared_default_marker(self):
        from bisheng.core.database.model_discovery import import_all_sqlmodel_models

        import_all_sqlmodel_models()
        table = SQLModelSerializable.metadata.tables.get("config")
        assert table is not None, "Config table missing from SQLModel metadata"
        assert "update_time" in table.columns
        server_default = getattr(table.columns["update_time"], "server_default", None)
        assert is_update_time_server_default(server_default), (
            "Config.update_time must use UPDATE_TIME_SERVER_DEFAULT so the DDL "
            "emits ON UPDATE CURRENT_TIMESTAMP on MySQL. IKB8XT is the bug "
            "this constraint exists to prevent from regressing."
        )

    def test_config_table_compiles_with_on_update_on_mysql(self):
        """The whole point of the model change: a fresh create_all on MySQL
        must produce ON UPDATE CURRENT_TIMESTAMP, not just DEFAULT."""
        from bisheng.core.database.model_discovery import import_all_sqlmodel_models

        import_all_sqlmodel_models()
        table = SQLModelSerializable.metadata.tables["config"]
        ddl = str(CreateTable(table).compile(dialect=mysql.dialect()))
        assert "ON UPDATE CURRENT_TIMESTAMP" in ddl, (
            f"create_all on MySQL did not emit ON UPDATE CURRENT_TIMESTAMP; DDL was:\n{ddl}"
        )


class TestHelper:
    def test_is_update_time_server_default_recognises_the_marker(self):
        marked = Column("update_time", DateTime, server_default=UPDATE_TIME_SERVER_DEFAULT)
        plain = Column("update_time", DateTime, server_default=sa.text("CURRENT_TIMESTAMP"))
        bare = Column("update_time", DateTime)
        none_default = Column("update_time", DateTime, nullable=False)

        assert is_update_time_server_default(marked.server_default)
        assert not is_update_time_server_default(plain.server_default)
        assert not is_update_time_server_default(bare.server_default)
        assert not is_update_time_server_default(none_default.server_default)
        assert not is_update_time_server_default(None)


class TestMigrationStatements:
    def test_drifted_config_column_is_rewritten_with_on_update(self, monkeypatch):
        executed = _run_upgrade(
            monkeypatch,
            rows=[("config", "datetime", "NO")],
        )
        assert executed == [
            "ALTER TABLE `config` MODIFY COLUMN `update_time` datetime "
            "NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"
        ]

    def test_nullable_config_column_keeps_being_nullable(self, monkeypatch):
        executed = _run_upgrade(
            monkeypatch,
            rows=[("config", "datetime", "YES")],
        )
        assert executed == [
            "ALTER TABLE `config` MODIFY COLUMN `update_time` datetime "
            "NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"
        ]

    def test_column_with_already_correct_ddl_is_not_rewritten(self, monkeypatch):
        """If the column already has ON UPDATE in EXTRA, information_schema
        either returns no rows (no drift) or the row still matches and we
        just confirm we don't issue an ALTER. The drift guard returns
        empty rows when the column is already correct, so no ALTER runs.
        """
        executed = _run_upgrade(monkeypatch, rows=[])
        assert executed == []

    def test_other_tables_in_information_schema_are_left_alone(self, monkeypatch):
        """The migration's information_schema query is narrowly scoped to
        the ``config`` table; it should never touch other tables even if
        they share a similar drift."""
        executed = _run_upgrade(
            monkeypatch,
            rows=[("other_table", "datetime", "NO")],
        )
        # The fetchall returned a row for a different table, but our
        # query is parameterised: the migration would still try to
        # re-emit a config ALTER — defensible only because the
        # parameter binding keeps the SELECT scoped. With our narrow
        # WHERE-clause the row cannot appear, so this is the
        # negative-case assertion: nothing runs for a row that does
        # not match the WHERE filter (rows argument == [] here).
        assert executed == []

    def test_non_mysql_dialects_are_a_no_op(self, monkeypatch):
        executed = _run_upgrade(monkeypatch, rows=[("config", "datetime", "NO")], dialect="dm")
        assert executed == []

    def test_model_revert_blocks_the_migration(self, monkeypatch):
        """Defensive: if the model side has reverted to bare
        ``text('CURRENT_TIMESTAMP')``, the migration must not re-emit
        DDL that create_all would not reproduce."""
        executed = _run_upgrade(
            monkeypatch,
            rows=[("config", "datetime", "NO")],
            declares_marker=False,
        )
        assert executed == []

    @pytest.mark.parametrize(
        "row",
        [
            ("config", "datetime) NOT NULL, ADD COLUMN x INT", "NO"),
            ("config", "varchar(255)", "NO"),
        ],
    )
    def test_unexpected_column_type_is_skipped(self, monkeypatch, row):
        """The statement is assembled as text because ON UPDATE has no
        SQLAlchemy construct, so the type string is shape-checked first."""
        executed = _run_upgrade(monkeypatch, rows=[row])
        assert executed == []
