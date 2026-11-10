"""Initial password for synced users, and the forced change at first login.

The policy: org-sync only fills accounts that have no password, never overwrites
one a user/admin set, and login refuses the shared value (10601) so the frontend
routes the user through the change-password page.
"""

from types import SimpleNamespace

import pytest

from bisheng.common.services.config_service import settings
from bisheng.sso_sync.domain.services.login_sync_service import LoginSyncService
from bisheng.user.domain.services.user import UserService
from bisheng.utils import md5_hash

INITIAL = "Initial#Passw0rd"  # neutral test value; the real one lives in config.yaml


@pytest.fixture()
def initial_pw(monkeypatch):
    monkeypatch.setattr(settings.sso_sync, "initial_password", INITIAL)
    return INITIAL


def test_hash_matches_md5_of_the_configured_value(initial_pw):
    assert LoginSyncService._initial_password_hash() == md5_hash(INITIAL)


def test_whitespace_is_trimmed(monkeypatch):
    monkeypatch.setattr(settings.sso_sync, "initial_password", f"  {INITIAL}  ")
    assert LoginSyncService._initial_password_hash() == md5_hash(INITIAL)


def test_feature_off_yields_no_hash(monkeypatch):
    monkeypatch.setattr(settings.sso_sync, "initial_password", "")
    assert LoginSyncService._initial_password_hash() == ""


def test_only_empty_passwords_are_filled(initial_pw):
    fresh = SimpleNamespace(password="", password_update_time=None)
    LoginSyncService._ensure_initial_password(fresh)
    assert fresh.password == md5_hash(INITIAL)
    assert fresh.password_update_time is not None

    owned = md5_hash("a-password-the-user-chose")
    changed = SimpleNamespace(password=owned, password_update_time=None)
    LoginSyncService._ensure_initial_password(changed)
    assert changed.password == owned
    assert changed.password_update_time is None


def test_nothing_is_filled_when_the_feature_is_off(monkeypatch):
    monkeypatch.setattr(settings.sso_sync, "initial_password", "")
    fresh = SimpleNamespace(password="", password_update_time=None)
    LoginSyncService._ensure_initial_password(fresh)
    assert fresh.password == ""


def test_login_detects_the_shared_initial_password(initial_pw):
    assert UserService._is_initial_password(md5_hash(INITIAL)) is True
    assert UserService._is_initial_password(md5_hash("something-else")) is False


def test_login_never_forces_a_change_when_the_feature_is_off(monkeypatch):
    monkeypatch.setattr(settings.sso_sync, "initial_password", "")
    assert UserService._is_initial_password(md5_hash(INITIAL)) is False
