"""Guards for the update_time server-default contract.

A table reaches a live database by two paths — ``create_all()`` on a fresh
install, the creating revision on an upgrade — and both must emit the same
``update_time`` DDL. They did not: several revisions wrote a plain
``CURRENT_TIMESTAMP`` (or no default at all) where the model declares
``UPDATE_TIME_SERVER_DEFAULT``, so upgraded MySQL databases silently lost the
``ON UPDATE CURRENT_TIMESTAMP`` half. On ``linsight_skill`` that produced NULL
update_time values and a skill list that sorted freshly imported skills last.

``update_time_default_align`` repairs existing databases. These tests keep the
two sides from drifting apart again: the model side must keep declaring the
shared default, and the migration must keep targeting exactly the tables that do.
"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, is_update_time_server_default

# test/database/test_update_time_default_alignment.py -> parents[2] == src/backend
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION = (
    _BACKEND_ROOT
    / "bisheng"
    / "core"
    / "database"
    / "alembic"
    / "versions"
    / "v3_0_0_beta1_update_time_default_align.py"
)

# Tables that deliberately declare a plain CURRENT_TIMESTAMP: their rows are
# rewritten wholesale by the service that owns them, so an automatic ON UPDATE
# would add nothing. They are consistent between model and DDL — which is the
# property under test — so they are recorded here rather than "fixed".
_PLAIN_DEFAULT_TABLES = {
    "config",
    "sensitive_word_policy",
    "tenant_system_model_config",
    "tenant_workstation_config",
}


def _load_migration():
    spec = importlib.util.spec_from_file_location("update_time_default_align", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, _stmt):
        return SimpleNamespace(fetchall=lambda: self._rows)


class _FakeOp:
    def __init__(self, conn):
        self._conn = conn
        self.executed: list[str] = []

    def get_bind(self):
        return self._conn

    def execute(self, sql):
        self.executed.append(str(sql))


def _run_upgrade(monkeypatch, rows, declared, dialect="mysql"):
    module = _load_migration()
    op = _FakeOp(_FakeConn(rows))
    monkeypatch.setattr(module, "op", op)
    monkeypatch.setattr(module, "get_dialect_name", lambda _conn: dialect)
    monkeypatch.setattr(module, "_tables_declaring_update_time_default", lambda: declared)
    module.upgrade()
    return op.executed


class TestModelDeclarations:
    """The model side is the source of truth the migration aligns towards."""

    def test_update_time_columns_declare_the_shared_default(self):
        from bisheng.common.models.base import SQLModelSerializable
        from bisheng.core.database.model_discovery import import_all_sqlmodel_models

        import_all_sqlmodel_models()
        offenders = sorted(
            table.name
            for table in SQLModelSerializable.metadata.tables.values()
            if "update_time" in table.columns
            and table.name not in _PLAIN_DEFAULT_TABLES
            and not is_update_time_server_default(table.columns["update_time"].server_default)
        )
        assert offenders == [], (
            f"These models declare update_time without UPDATE_TIME_SERVER_DEFAULT: {offenders}. "
            "Use it so create_all() and the migration emit the same DDL, or add the table to "
            "_PLAIN_DEFAULT_TABLES with the reason it opts out."
        )

    def test_migration_selects_the_declaring_tables(self):
        declared = _load_migration()._tables_declaring_update_time_default()
        # linsight_skill is the table whose drift produced the reported bug.
        assert "linsight_skill" in declared
        assert "knowledge_document" in declared
        assert declared.isdisjoint(_PLAIN_DEFAULT_TABLES)
        # Tables owned by the Java gateway have no SQLModel and must be left alone.
        assert not any(name.startswith("gt_") for name in declared)


class TestMigrationStatements:
    def test_nullable_column_keeps_being_nullable(self, monkeypatch):
        executed = _run_upgrade(
            monkeypatch,
            rows=[("linsight_skill", "datetime", "YES")],
            declared={"linsight_skill"},
        )
        assert executed == [
            "ALTER TABLE `linsight_skill` MODIFY COLUMN `update_time` datetime "
            "NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"
        ]

    def test_not_null_column_keeps_being_not_null(self, monkeypatch):
        executed = _run_upgrade(
            monkeypatch,
            rows=[("knowledge_document", "datetime", "NO")],
            declared={"knowledge_document"},
        )
        assert "NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP" in executed[0]

    def test_tables_no_model_declares_are_left_alone(self, monkeypatch):
        """The drift query returns every table in the schema, including ones
        another component owns; only declared tables may be altered."""
        executed = _run_upgrade(
            monkeypatch,
            rows=[("gt_block_record", "datetime", "NO"), ("linsight_skill", "datetime", "YES")],
            declared={"linsight_skill"},
        )
        assert len(executed) == 1
        assert "linsight_skill" in executed[0]

    @pytest.mark.parametrize(
        "row",
        [
            ("bad name; DROP TABLE x", "datetime", "NO"),
            ("linsight_skill", "datetime) NOT NULL, ADD COLUMN x INT", "NO"),
        ],
    )
    def test_identifiers_that_are_not_plain_are_skipped(self, monkeypatch, row):
        """The statement is assembled as text because ON UPDATE has no SQLAlchemy
        construct, so the identifiers it interpolates are shape-checked first."""
        executed = _run_upgrade(monkeypatch, rows=[row], declared={row[0]})
        assert executed == []

    def test_non_mysql_dialects_are_a_no_op(self, monkeypatch):
        """DaMeng gets ON UPDATE from boot-time triggers instead."""
        executed = _run_upgrade(
            monkeypatch,
            rows=[("linsight_skill", "datetime", "YES")],
            declared={"linsight_skill"},
            dialect="dm",
        )
        assert executed == []


class TestHelper:
    def test_recognises_the_marker_and_nothing_else(self):
        import sqlalchemy as sa
        from sqlalchemy import Column, DateTime

        marked = Column("update_time", DateTime, server_default=UPDATE_TIME_SERVER_DEFAULT)
        plain = Column("update_time", DateTime, server_default=sa.text("CURRENT_TIMESTAMP"))
        bare = Column("update_time", DateTime)

        assert is_update_time_server_default(marked.server_default)
        assert not is_update_time_server_default(plain.server_default)
        assert not is_update_time_server_default(bare.server_default)
