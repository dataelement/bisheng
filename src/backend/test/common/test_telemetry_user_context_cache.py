"""D1: telemetry user-context is cached per user_id with a TTL.

The per-event user context (user + groups + roles + departments — a 4-query
selectin join) is identical for a given user and was previously re-fetched on
every model invoke, dominating CPU/GIL under load. These tests lock the cache
behavior: a second lookup within the TTL reuses the first result (no DB hit),
the entry expires after the TTL, and the async/sync paths share one cache.
"""

import sys
from unittest.mock import MagicMock

# Stub native deps the real telemetry module imports at top level, then drop the
# conftest blanket pre-mock so the *real* module loads (mirrors
# test_telemetry_thread_context).
for _mod in ("elasticsearch", "elasticsearch.exceptions"):
    if _mod not in sys.modules or isinstance(sys.modules[_mod], MagicMock):
        sys.modules.setdefault(_mod, MagicMock())

for _mod in (
    "bisheng.common.services.telemetry.telemetry_service",
    "bisheng.common.services.telemetry",
    "bisheng.common.services",
):
    sys.modules.pop(_mod, None)

import importlib  # noqa: E402

import pytest  # noqa: E402

from bisheng.common.schemas.telemetry.base_telemetry_schema import UserContext  # noqa: E402

# Reference the live module object (not a string path). Both this file and
# test_telemetry_thread_context pop+reload the telemetry module; resolving the
# class and the monkeypatch targets through the same module object keeps them
# consistent regardless of cross-file import order.
ts = importlib.import_module("bisheng.common.services.telemetry.telemetry_service")
BaseTelemetryService = ts.BaseTelemetryService


class _FakeUser:
    def __init__(self, user_id):
        self.user_id = user_id
        self.user_name = f"user-{user_id}"
        self.groups = []
        self.roles = []
        self.departments = []


class _FakeSyncSession:
    def __enter__(self):
        return object()

    def __exit__(self, *a):
        return False


class _FakeAsyncSession:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *a):
        return False


@pytest.fixture(autouse=True)
def _clear_cache():
    BaseTelemetryService._user_context_cache.clear()
    yield
    BaseTelemetryService._user_context_cache.clear()


def _patch_sync_repo(monkeypatch, counter):
    class _Repo:
        def __init__(self, session):
            pass

        def get_user_with_groups_and_roles_by_user_id_sync(self, user_id):
            counter["n"] += 1
            return _FakeUser(user_id)

    monkeypatch.setattr(ts, "get_sync_db_session", lambda: _FakeSyncSession())
    monkeypatch.setattr(ts, "UserRepositoryImpl", _Repo)


def test_sync_user_context_cached_within_ttl(monkeypatch):
    counter = {"n": 0}
    _patch_sync_repo(monkeypatch, counter)

    first = BaseTelemetryService._init_user_context_sync(555)
    second = BaseTelemetryService._init_user_context_sync(555)

    assert counter["n"] == 1, "second lookup within TTL must not re-query the DB"
    assert first is second
    assert first == UserContext(user_id=555, user_name="user-555")


def test_sync_user_context_refetched_after_ttl(monkeypatch):
    counter = {"n": 0}
    _patch_sync_repo(monkeypatch, counter)

    BaseTelemetryService._init_user_context_sync(556)
    # Force the cached entry to be expired without waiting the real TTL.
    monkeypatch.setattr(BaseTelemetryService, "_USER_CONTEXT_TTL_SECONDS", -1.0)
    BaseTelemetryService._store_cached_user_context(556, UserContext(user_id=556, user_name="stale"))

    refetched = BaseTelemetryService._init_user_context_sync(556)

    assert counter["n"] == 2, "expired entry must trigger a fresh DB lookup"
    assert refetched == UserContext(user_id=556, user_name="user-556")


@pytest.mark.asyncio
async def test_async_populates_cache_then_sync_hits_it(monkeypatch):
    async_counter = {"n": 0}
    sync_counter = {"n": 0}

    class _AsyncRepo:
        def __init__(self, session):
            pass

        async def get_user_with_groups_and_roles_by_user_id(self, user_id):
            async_counter["n"] += 1
            return _FakeUser(user_id)

    class _SyncRepo:
        def __init__(self, session):
            pass

        def get_user_with_groups_and_roles_by_user_id_sync(self, user_id):
            sync_counter["n"] += 1
            return _FakeUser(user_id)

    monkeypatch.setattr(ts, "get_async_db_session", lambda: _FakeAsyncSession())
    monkeypatch.setattr(ts, "get_sync_db_session", lambda: _FakeSyncSession())
    # The async path resolves first and populates the shared cache.
    monkeypatch.setattr(ts, "UserRepositoryImpl", _AsyncRepo)
    ctx_async = await BaseTelemetryService._init_user_context(777)

    # The sync path must hit the cache and never construct/query its repo.
    monkeypatch.setattr(ts, "UserRepositoryImpl", _SyncRepo)
    ctx_sync = BaseTelemetryService._init_user_context_sync(777)

    assert async_counter["n"] == 1
    assert sync_counter["n"] == 0, "sync path should reuse the async-populated cache entry"
    assert ctx_async is ctx_sync
