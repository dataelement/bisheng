"""AC-34/49/54: schema CAS storage stays independent of model/default revisions."""

import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateColumn

from bisheng.knowledge.domain.models.knowledge import Knowledge


def migration():
    path = Path(__file__).resolve().parents[2] / "bisheng/core/database/alembic/versions/f118_metadata_schema.py"
    spec = importlib.util.spec_from_file_location("f118_metadata_schema_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_private_schema_revision_starts_at_zero_independently():
    row = Knowledge(name="schema-cas", model_config_revision=7, processing_config_version=9)
    assert row.metadata_schema_revision == 0
    assert "metadata_schema_revision" not in row.model_dump()
    column = Knowledge.__table__.c.metadata_schema_revision
    assert column.nullable is False
    assert str(column.server_default.arg) == "0"
    assert "DEFAULT 0" in str(CreateColumn(column).compile(dialect=mysql.dialect()))


def test_revision_chains_after_the_verified_previous_head():
    module = migration()
    assert module.revision == "f118_metadata_schema"
    assert module.down_revision == "f118_knowledge_unification"


@pytest.mark.parametrize("has_table,has_column,expected", [(True, False, 1), (True, True, 0), (False, False, 0)])
def test_upgrade_only_adds_the_missing_column(monkeypatch, has_table, has_column, expected):
    module = migration()
    add = Mock()
    monkeypatch.setattr(module, "table_exists", lambda name: has_table)
    monkeypatch.setattr(module, "column_exists", lambda table, name: has_column)
    monkeypatch.setattr(module.op, "add_column", add)
    module.upgrade()
    assert add.call_count == expected
    if expected:
        table, column = add.call_args.args
        assert (table, column.name) == ("knowledge", "metadata_schema_revision")
        assert column.nullable is False
        assert str(column.server_default.arg) == "0"


def test_downgrade_does_not_erase_live_job_revision_evidence():
    with pytest.raises(RuntimeError, match="backup"):
        migration().downgrade()
