"""F072: JWT signing secret must never be the shipped default.

Resolution order: config.yaml ``jwt_secret`` (unless it is a leaked legacy
value) → generated-once secret persisted in the ``config`` table.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from bisheng.user.domain.services import jwt_secret as m


@pytest.fixture(autouse=True)
def _reset_cache():
    m.reset_cache()
    yield
    m.reset_cache()


def _settings(monkeypatch, value):
    # Patch the resolver's own settings lookup rather than ``config_service.settings``:
    # several legacy tests pop / re-import ``bisheng.common.services`` at import
    # time, so which module object a dotted path resolves to depends on run order.
    monkeypatch.setattr(m, "_settings_object", lambda: SimpleNamespace(jwt_secret=value))


def _forbid_db(monkeypatch):
    def _boom():
        raise AssertionError("database must not be consulted")

    monkeypatch.setattr(m, "_load_or_create_db_secret", _boom)


def test_yaml_secret_is_used_without_touching_db(monkeypatch):
    _settings(monkeypatch, "operator-private-secret")
    _forbid_db(monkeypatch)
    assert m.resolve_jwt_secret() == "operator-private-secret"


@pytest.mark.parametrize("legacy", sorted(m.LEGACY_JWT_SECRETS))
def test_legacy_default_in_yaml_is_treated_as_unset(monkeypatch, legacy):
    _settings(monkeypatch, legacy)
    monkeypatch.setattr(m, "_load_or_create_db_secret", lambda: "generated-secret")
    assert m.resolve_jwt_secret() == "generated-secret"


@pytest.mark.parametrize("value", ["", "   ", None, MagicMock()])
def test_unset_yaml_falls_back_to_generated_secret(monkeypatch, value):
    _settings(monkeypatch, value)
    monkeypatch.setattr(m, "_load_or_create_db_secret", lambda: "generated-secret")
    assert m.resolve_jwt_secret() == "generated-secret"


def test_generated_secret_is_cached_per_process(monkeypatch):
    _settings(monkeypatch, "")
    calls = []

    def _load():
        calls.append(1)
        return "generated-secret"

    monkeypatch.setattr(m, "_load_or_create_db_secret", _load)
    assert m.resolve_jwt_secret() == "generated-secret"
    assert m.resolve_jwt_secret() == "generated-secret"
    assert len(calls) == 1


def test_yaml_value_is_read_live_not_cached(monkeypatch):
    _settings(monkeypatch, "first")
    assert m.resolve_jwt_secret() == "first"
    _settings(monkeypatch, "second")
    assert m.resolve_jwt_secret() == "second"


class _FakeSession:
    def __init__(self, fail_commit=None):
        self.added = []
        self.fail_commit = fail_commit

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def add(self, row):
        self.added.append(row)

    def commit(self):
        if self.fail_commit:
            raise self.fail_commit


def test_existing_db_row_is_reused(monkeypatch):
    from bisheng.common.models import config as config_mod

    monkeypatch.setattr(
        config_mod.ConfigDao, "get_config", classmethod(lambda cls, key: SimpleNamespace(value="db-secret"))
    )
    monkeypatch.setattr(
        "bisheng.core.database.get_sync_db_session", lambda: (_ for _ in ()).throw(AssertionError("no insert"))
    )
    assert m._load_or_create_db_secret() == "db-secret"


def test_missing_db_row_generates_and_persists(monkeypatch):
    from bisheng.common.models import config as config_mod

    session = _FakeSession()
    monkeypatch.setattr(config_mod.ConfigDao, "get_config", classmethod(lambda cls, key: None))
    monkeypatch.setattr("bisheng.core.database.get_sync_db_session", lambda: session)

    secret = m._load_or_create_db_secret()

    assert len(session.added) == 1
    row = session.added[0]
    assert row.key == config_mod.ConfigKeyEnum.JWT_SECRET.value
    assert row.value == secret
    assert len(secret) >= 32
    assert secret not in m.LEGACY_JWT_SECRETS


def test_first_boot_race_returns_winner(monkeypatch):
    from bisheng.common.models import config as config_mod

    reads = iter([None, SimpleNamespace(value="winner-secret")])
    monkeypatch.setattr(config_mod.ConfigDao, "get_config", classmethod(lambda cls, key: next(reads)))
    session = _FakeSession(fail_commit=IntegrityError("insert", {}, Exception("dup")))
    monkeypatch.setattr("bisheng.core.database.get_sync_db_session", lambda: session)

    assert m._load_or_create_db_secret() == "winner-secret"


def test_settings_ships_no_default_secret():
    from bisheng.core.config.settings import Settings

    assert Settings.model_fields["jwt_secret"].default == ""
