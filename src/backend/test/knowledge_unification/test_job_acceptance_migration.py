"""AC-49/54: upgrades preserve missing acceptance evidence without inventing it."""

import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest


def migration():
    path = Path(__file__).resolve().parents[2] / "bisheng/core/database/alembic/versions/f118_processing_acceptance.py"
    spec = importlib.util.spec_from_file_location("f118_processing_acceptance_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_chains_after_the_verified_metadata_schema_head():
    module = migration()
    assert module.revision == "f118_processing_acceptance"
    assert module.down_revision == "f118_metadata_schema"


@pytest.mark.parametrize("has_table,has_column,expected", [(True, False, 1), (True, True, 0), (False, False, 0)])
def test_only_adds_missing_nullable_audit_column(monkeypatch, has_table, has_column, expected):
    module = migration()
    add = Mock()
    monkeypatch.setattr(module, "table_exists", lambda table: has_table)
    monkeypatch.setattr(module, "column_exists", lambda table, column: has_column)
    monkeypatch.setattr(module.op, "add_column", add)
    module.upgrade()
    assert add.call_count == expected
    if expected:
        table, column = add.call_args.args
        assert (table, column.name) == ("knowledge_processing_job", "accepted_model_config_revision")
        assert column.nullable is True
        assert column.server_default is None


def test_downgrade_cannot_drop_audit_evidence_under_live_jobs():
    with pytest.raises(RuntimeError, match="backup"):
        migration().downgrade()
