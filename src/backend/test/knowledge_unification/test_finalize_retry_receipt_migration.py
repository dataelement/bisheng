"""AC-49/50/54: only known retry CHECK metadata is upgraded, never task rows."""

import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest


def migration():
    path = Path(__file__).resolve().parents[2] / "bisheng/core/database/alembic/versions/f118_finalize_retry.py"
    spec = importlib.util.spec_from_file_location("f118_finalize_retry_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parent_is_the_verified_processing_acceptance_head():
    module = migration()
    assert module.revision == "f118_finalize_retry"
    assert module.down_revision == "f118_processing_acceptance"


@pytest.mark.parametrize("old", [True, False])
def test_known_check_is_replaced_once_with_case_folded_metadata(monkeypatch, old):
    module = migration()
    expression = module.OLD_CHECK if old else module.NEW_CHECK
    existing = {"name": "CK_KPR_REVISION", "sqltext": " (" + expression.upper() + ") "}
    monkeypatch.setattr(module, "table_exists", lambda table: True)
    monkeypatch.setattr(module, "get_check_constraint", lambda table, name: existing)
    create, drop = Mock(), Mock()
    monkeypatch.setattr(module.op, "create_check_constraint", create)
    monkeypatch.setattr(module.op, "drop_constraint", drop)
    monkeypatch.setattr(module.op, "execute", Mock(side_effect=AssertionError("no business data SQL")))
    module.upgrade()
    assert create.call_count == drop.call_count == int(old)
    if old:
        drop.assert_called_once_with("CK_KPR_REVISION", module.TABLE, type_="check")
        create.assert_called_once_with("ck_kpr_revision", module.TABLE, module.NEW_CHECK)


def test_missing_table_is_left_to_model_discovery(monkeypatch):
    module = migration()
    monkeypatch.setattr(module, "table_exists", lambda table: False)
    monkeypatch.setattr(module, "get_check_constraint", Mock(side_effect=AssertionError("no reflection needed")))
    module.upgrade()


def test_missing_check_is_created_without_altering_rows(monkeypatch):
    module = migration()
    monkeypatch.setattr(module, "table_exists", lambda table: True)
    monkeypatch.setattr(module, "get_check_constraint", lambda table, name: None)
    create = Mock()
    monkeypatch.setattr(module.op, "create_check_constraint", create)
    module.upgrade()
    create.assert_called_once_with("ck_kpr_revision", module.TABLE, module.NEW_CHECK)


def test_unknown_existing_definition_fails_without_drop(monkeypatch):
    module = migration()
    monkeypatch.setattr(module, "table_exists", lambda table: True)
    monkeypatch.setattr(
        module, "get_check_constraint", lambda table, name: {"name": name, "sqltext": "item_count > 10"}
    )
    drop = Mock()
    monkeypatch.setattr(module.op, "drop_constraint", drop)
    with pytest.raises(RuntimeError, match="unexpected"):
        module.upgrade()
    drop.assert_not_called()


def test_rollback_requires_the_consistent_backup():
    with pytest.raises(RuntimeError, match="backup"):
        migration().downgrade()
