"""F120 — first-user super-admin bootstrap guard inside LoginSyncService."""

from types import SimpleNamespace

import pytest
from redis.exceptions import RedisError

from bisheng.sso_sync.domain.services import login_sync_service as mod


class _Conn:
    def __init__(self, acquire: bool = True, error: Exception | None = None) -> None:
        self._acquire = acquire
        self._error = error

    async def set(self, key, value, nx=None, ex=None):
        if self._error is not None:
            raise self._error
        return self._acquire


@pytest.fixture
def redis_guard(monkeypatch):
    def _install(*, acquire=True, error=None):
        async def _get_redis_client():
            return SimpleNamespace(async_connection=_Conn(acquire, error))

        monkeypatch.setattr(mod, "get_redis_client", _get_redis_client)

    return _install


def _users(monkeypatch, rows):
    monkeypatch.setattr(mod.UserDao, "get_all_users", classmethod(lambda cls, page=0, limit=0: rows))


async def test_bootstrap_allowed_only_once_on_an_empty_platform(redis_guard, monkeypatch):
    redis_guard(acquire=True)
    _users(monkeypatch, [])

    assert await mod.LoginSyncService._claim_first_user_bootstrap() is True


async def test_bootstrap_refused_when_platform_already_has_users(redis_guard, monkeypatch):
    redis_guard(acquire=True)
    _users(monkeypatch, [object()])

    assert await mod.LoginSyncService._claim_first_user_bootstrap() is False


async def test_bootstrap_refused_when_another_login_holds_the_guard(redis_guard, monkeypatch):
    redis_guard(acquire=False)
    _users(monkeypatch, [])

    assert await mod.LoginSyncService._claim_first_user_bootstrap() is False


async def test_bootstrap_fails_closed_when_redis_is_down(redis_guard, monkeypatch):
    redis_guard(error=RedisError("down"))
    _users(monkeypatch, [])

    assert await mod.LoginSyncService._claim_first_user_bootstrap() is False
