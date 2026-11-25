"""F016 migration: additive, repeatable, matches the model, refuses destructive downgrade."""

from unittest.mock import Mock

import pytest

from test.database.test_alembic_single_head import _script_directory


def _revision():
    return _script_directory().get_revision("v310b1_f016_dsh_call_pricing").module


def test_f016_is_on_the_single_head_lineage():
    # Later revisions may land on top of F016; it only has to stay on the one head's chain.
    script = _script_directory()
    heads = script.get_heads()
    assert len(heads) == 1
    lineage = {rev.revision for rev in script.walk_revisions(base="base", head=heads[0])}
    assert "v310b1_f016_dsh_call_pricing" in lineage


def test_columns_match_the_model_on_mysql():
    """Offline MySQL compilation is parity evidence, not a real database upgrade."""
    from sqlalchemy.dialects.mysql import dialect
    from sqlalchemy.schema import CreateColumn

    from bisheng.dsh.domain.models.model_call import DshModelCall

    for column in _revision()._columns():
        expected = DshModelCall.__table__.c[column.name]
        assert str(CreateColumn(column).compile(dialect=dialect())) == str(
            CreateColumn(expected).compile(dialect=dialect())
        ), column.name


@pytest.mark.parametrize("present", [set(), {"pricing"}, {"pricing", "cost_micro", "currency"}])
def test_upgrade_adds_only_missing_columns_and_is_repeatable(monkeypatch, present):
    revision = _revision()
    columns = set(present)
    operations = Mock()
    operations.add_column.side_effect = lambda table, column: columns.add(column.name)
    monkeypatch.setattr(revision, "op", operations)
    monkeypatch.setattr(revision, "table_exists", lambda table: table == "dsh_model_call")
    monkeypatch.setattr(revision, "column_exists", lambda table, name: name in columns)
    revision.upgrade()
    assert columns == {"pricing", "cost_micro", "currency"}
    assert operations.add_column.call_count == 3 - len(present)
    operations.reset_mock()
    revision.upgrade()
    operations.add_column.assert_not_called()
    operations.execute.assert_not_called()


def test_upgrade_skips_when_the_table_is_created_fresh(monkeypatch):
    revision = _revision()
    operations = Mock()
    monkeypatch.setattr(revision, "op", operations)
    monkeypatch.setattr(revision, "table_exists", lambda table: False)
    revision.upgrade()
    assert not operations.mock_calls


def test_downgrade_refuses_to_drop_price_evidence(monkeypatch):
    revision = _revision()
    operations = Mock()
    monkeypatch.setattr(revision, "op", operations)
    with pytest.raises(RuntimeError, match="must be retained"):
        revision.downgrade()
    assert not operations.mock_calls
