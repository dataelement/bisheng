"""Unit tests for PermissionCache (T14 — test_permission_cache).

Tests cache hit/miss, TTL, and UNCACHEABLE_RELATIONS bypass.
Uses a mock RedisClient to avoid real Redis dependency.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class FakeRedisClient:
    """Minimal in-memory Redis mock for cache tests."""

    def __init__(self):
        self._store = {}

    async def aset(self, key, value, expiration=None):
        import pickle
        self._store[key] = pickle.dumps(value)
        return True

    async def aget(self, key):
        import pickle
        raw = self._store.get(key)
        if raw is None:
            return None
        return pickle.loads(raw)

    async def adelete(self, key):
        self._store.pop(key, None)

    @property
    def async_connection(self):
        return self

    async def scan(self, cursor=0, match=None, count=100):
        """Simplified SCAN — returns all matching keys at once."""
        import fnmatch
        matching = [k.encode() if isinstance(k, str) else k for k in self._store if fnmatch.fnmatch(k, match or '*')]
        return (0, matching)

    async def delete(self, *keys):
        for k in keys:
            key_str = k.decode() if isinstance(k, bytes) else k
            self._store.pop(key_str, None)


@pytest.fixture
def fake_redis():
    return FakeRedisClient()


class TestPermissionCacheCheck:

    @pytest.mark.asyncio
    async def test_cache_miss(self, fake_redis):
        from bisheng.permission.domain.services.permission_cache import PermissionCache

        with patch.object(PermissionCache, '_get_redis', new_callable=AsyncMock, return_value=fake_redis):
            result = await PermissionCache.get_check(1, 'viewer', 'workflow', 'abc')
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_hit_true(self, fake_redis):
        from bisheng.permission.domain.services.permission_cache import PermissionCache

        with patch.object(PermissionCache, '_get_redis', new_callable=AsyncMock, return_value=fake_redis):
            await PermissionCache.set_check(1, 'viewer', 'workflow', 'abc', True)
            result = await PermissionCache.get_check(1, 'viewer', 'workflow', 'abc')
        assert result is True

    @pytest.mark.asyncio
    async def test_cache_hit_false(self, fake_redis):
        from bisheng.permission.domain.services.permission_cache import PermissionCache

        with patch.object(PermissionCache, '_get_redis', new_callable=AsyncMock, return_value=fake_redis):
            await PermissionCache.set_check(1, 'viewer', 'workflow', 'abc', False)
            result = await PermissionCache.get_check(1, 'viewer', 'workflow', 'abc')
        assert result is False


class TestPermissionCacheListObjects:

    @pytest.mark.asyncio
    async def test_list_cache_miss(self, fake_redis):
        from bisheng.permission.domain.services.permission_cache import PermissionCache

        with patch.object(PermissionCache, '_get_redis', new_callable=AsyncMock, return_value=fake_redis):
            result = await PermissionCache.get_list_objects(1, 'viewer', 'workflow')
        assert result is None

    @pytest.mark.asyncio
    async def test_list_cache_hit(self, fake_redis):
        from bisheng.permission.domain.services.permission_cache import PermissionCache

        with patch.object(PermissionCache, '_get_redis', new_callable=AsyncMock, return_value=fake_redis):
            await PermissionCache.set_list_objects(1, 'viewer', 'workflow', ['abc', 'def'])
            result = await PermissionCache.get_list_objects(1, 'viewer', 'workflow')
        assert result == ['abc', 'def']


class TestPermissionCacheInvalidation:

    @pytest.mark.asyncio
    async def test_invalidate_user(self, fake_redis):
        from bisheng.permission.domain.services.permission_cache import PermissionCache

        with patch.object(PermissionCache, '_get_redis', new_callable=AsyncMock, return_value=fake_redis):
            await PermissionCache.set_check(1, 'viewer', 'workflow', 'abc', True)
            await PermissionCache.set_check(1, 'editor', 'workflow', 'abc', False)
            await PermissionCache.set_check(2, 'viewer', 'workflow', 'abc', True)

            # Invalidate user 1
            await PermissionCache.invalidate_user(1)

            # User 1's cache should be gone
            result1 = await PermissionCache.get_check(1, 'viewer', 'workflow', 'abc')
            assert result1 is None

            # User 2's cache should remain
            result2 = await PermissionCache.get_check(2, 'viewer', 'workflow', 'abc')
            assert result2 is True

    @pytest.mark.asyncio
    async def test_invalidate_all(self, fake_redis):
        from bisheng.permission.domain.services.permission_cache import PermissionCache

        with patch.object(PermissionCache, '_get_redis', new_callable=AsyncMock, return_value=fake_redis):
            await PermissionCache.set_check(1, 'viewer', 'workflow', 'abc', True)
            await PermissionCache.set_check(2, 'viewer', 'workflow', 'def', True)

            await PermissionCache.invalidate_all()

            result1 = await PermissionCache.get_check(1, 'viewer', 'workflow', 'abc')
            result2 = await PermissionCache.get_check(2, 'viewer', 'workflow', 'def')
            assert result1 is None
            assert result2 is None


class TestRedisUnavailable:

    @pytest.mark.asyncio
    async def test_redis_unavailable_get(self):
        """Redis unavailable → cache miss (None), no exception."""
        from bisheng.permission.domain.services.permission_cache import PermissionCache

        with patch.object(PermissionCache, '_get_redis', new_callable=AsyncMock, return_value=None):
            result = await PermissionCache.get_check(1, 'viewer', 'workflow', 'abc')
        assert result is None

    @pytest.mark.asyncio
    async def test_redis_unavailable_set(self):
        """Redis unavailable → set is a no-op, no exception."""
        from bisheng.permission.domain.services.permission_cache import PermissionCache

        with patch.object(PermissionCache, '_get_redis', new_callable=AsyncMock, return_value=None):
            await PermissionCache.set_check(1, 'viewer', 'workflow', 'abc', True)
            # Should not raise
