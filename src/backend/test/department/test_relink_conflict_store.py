"""Tests for F015 :class:`RelinkConflictStore`.

The store is a thin wrapper over a Redis HASH; the tests drive it with
an in-memory fake whose API mirrors the subset we actually call
(``hset``, ``hgetall``, ``expire``, ``delete``). End-to-end
behaviour inside :class:`DepartmentRelinkService` is covered by
``test_department_relink_service.py`` — here we verify the store itself
preserves round-trip fidelity, clears on delete, honours TTL, and
replaces stale entries instead of appending.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


MODULE = 'bisheng.org_sync.domain.services.relink_conflict_store'


class _FakeRedisHash:
    """Async-compatible stand-in for the Redis HASH API.

    Stores per-key dicts of field→value; records the ex= argument of the
    most recent expire call so tests can assert the 7-day TTL.
    """

    def __init__(self):
        self._data: dict[str, dict[str, bytes]] = {}
        self._ttls: dict[str, int] = {}
        self.async_connection = self

    async def hset(self, key, mapping=None):
        existing = self._data.setdefault(key, {})
        existing.update({
            k: (v if isinstance(v, bytes) else v.encode())
            for k, v in (mapping or {}).items()
        })
        return len(mapping or {})

    async def hgetall(self, key):
        return dict(self._data.get(key, {}))

    async def delete(self, *keys):
        removed = 0
        for k in keys:
            if k in self._data:
                del self._data[k]
                removed += 1
            self._ttls.pop(k, None)
        return removed

    async def expire(self, key, ex):
        self._ttls[key] = ex
        return True


@pytest.fixture()
def fake_store(monkeypatch):
    """Patch ``get_redis_client`` + ``settings`` so the store is self-contained."""
    fake_redis = _FakeRedisHash()

    async def _get_client():
        return fake_redis

    monkeypatch.setattr(f'{MODULE}.get_redis_client', _get_client)

    fake_settings = SimpleNamespace(
        reconcile=SimpleNamespace(relink_conflict_ttl_seconds=604_800),
    )
    monkeypatch.setattr(f'{MODULE}.settings', fake_settings)
    return fake_redis


@pytest.mark.asyncio
class TestRelinkConflictStore:

    async def test_save_and_get_returns_candidates_list(self, fake_store):
        from bisheng.org_sync.domain.services.relink_conflict_store import (
            RelinkConflictStore,
        )
        candidates = [
            {'new_external_id': 'NEW-1', 'path': '/A', 'name': 'A'},
            {'new_external_id': 'NEW-2', 'path': '/A', 'name': 'A'},
        ]
        await RelinkConflictStore.save(5, candidates)
        got = await RelinkConflictStore.get(5)
        got_by_ext = {c['new_external_id'] for c in got}
        assert got_by_ext == {'NEW-1', 'NEW-2'}
        # round-trip preserves payload shape
        assert all('path' in c and 'name' in c for c in got)

    async def test_save_sets_ttl_7_days(self, fake_store):
        from bisheng.org_sync.domain.services.relink_conflict_store import (
            RelinkConflictStore,
        )
        await RelinkConflictStore.save(
            7, [{'new_external_id': 'X', 'path': '/', 'name': 'X'}],
        )
        assert fake_store._ttls['relink_conflict:7'] == 604_800

    async def test_get_returns_empty_after_delete(self, fake_store):
        from bisheng.org_sync.domain.services.relink_conflict_store import (
            RelinkConflictStore,
        )
        await RelinkConflictStore.save(
            8, [{'new_external_id': 'X', 'path': '/', 'name': 'X'}],
        )
        assert await RelinkConflictStore.get(8) != []
        await RelinkConflictStore.delete(8)
        assert await RelinkConflictStore.get(8) == []

    async def test_get_returns_empty_when_no_entry(self, fake_store):
        from bisheng.org_sync.domain.services.relink_conflict_store import (
            RelinkConflictStore,
        )
        assert await RelinkConflictStore.get(9999) == []

    async def test_save_replaces_existing_entry_instead_of_appending(
        self, fake_store,
    ):
        """Re-saving for the same dept_id must reset the candidate set,
        not merge with the stale one — otherwise operators would see old
        candidates bleed into new runs after an SSO migration retry."""
        from bisheng.org_sync.domain.services.relink_conflict_store import (
            RelinkConflictStore,
        )
        await RelinkConflictStore.save(11, [
            {'new_external_id': 'OLD', 'path': '/x', 'name': 'x'},
        ])
        await RelinkConflictStore.save(11, [
            {'new_external_id': 'NEW', 'path': '/y', 'name': 'y'},
        ])
        got = await RelinkConflictStore.get(11)
        assert [c['new_external_id'] for c in got] == ['NEW']
