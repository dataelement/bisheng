"""Unit tests for SpaceListCache (Task 5 — per-user short-TTL cache for
`_list_accessible_spaces`).

Tests roundtrip fidelity, cache-miss behavior, and graceful degradation when
Redis is unavailable, using a minimal in-memory fake Redis client.
"""

from datetime import datetime

import pytest
from unittest.mock import AsyncMock, patch

from bisheng.knowledge.domain.services.space_list_cache import SpaceListCache, SPACE_LIST_CACHE_TTL


class _FakeRedis:
    def __init__(self):
        self.store = {}

    async def aget(self, key):
        return self.store.get(key)

    async def aset(self, key, value, expiration=None):
        self.store[key] = value


@pytest.mark.asyncio
async def test_set_then_get_roundtrip_preserves_fields():
    from bisheng.common.models.space_channel_member import UserRoleEnum
    from bisheng.knowledge.domain.models.knowledge_space_scope import (
        KnowledgeSpaceLevelEnum,
        KnowledgeSpaceOwnerTypeEnum,
    )
    from bisheng.knowledge.domain.schemas.knowledge_space_schema import KnowledgeSpaceInfoResp

    fake = _FakeRedis()
    non_default_update_time = datetime(2026, 1, 2, 3, 4, 5)
    space = KnowledgeSpaceInfoResp(
        id=3,
        name='n',
        user_id=88,
        user_role=UserRoleEnum.ADMIN,
        space_level=KnowledgeSpaceLevelEnum.DEPARTMENT,
        owner_type=KnowledgeSpaceOwnerTypeEnum.DEPARTMENT,
        update_time=non_default_update_time,
    )
    # Sanity-check the fixture itself isn't accidentally using schema defaults,
    # so the round-trip assertions below actually exercise non-default values.
    assert space.user_role != UserRoleEnum.MEMBER
    assert space.space_level != KnowledgeSpaceLevelEnum.PERSONAL
    assert space.owner_type != KnowledgeSpaceOwnerTypeEnum.USER
    with patch('bisheng.knowledge.domain.services.space_list_cache.get_redis_client',
               new_callable=AsyncMock, return_value=fake):
        await SpaceListCache.set(7, 'update_time', [space])
        got = await SpaceListCache.get(7, 'update_time')
    assert got is not None
    assert [s.id for s in got] == [3]
    assert got[0].name == 'n'
    assert got[0].user_id == 88
    assert got[0].space_level == KnowledgeSpaceLevelEnum.DEPARTMENT
    assert got[0].user_role == UserRoleEnum.ADMIN
    assert got[0].owner_type == KnowledgeSpaceOwnerTypeEnum.DEPARTMENT
    assert got[0].update_time == non_default_update_time


@pytest.mark.asyncio
async def test_get_miss_returns_none():
    fake = _FakeRedis()
    with patch('bisheng.knowledge.domain.services.space_list_cache.get_redis_client',
               new_callable=AsyncMock, return_value=fake):
        assert await SpaceListCache.get(7, 'update_time') is None


@pytest.mark.asyncio
async def test_cached_empty_list_is_a_hit_not_a_miss():
    """A user with zero accessible spaces should still get a real cache hit
    (an empty list), not be treated as a cache miss that forces a recompute.
    """
    fake = _FakeRedis()
    with patch('bisheng.knowledge.domain.services.space_list_cache.get_redis_client',
               new_callable=AsyncMock, return_value=fake):
        await SpaceListCache.set(7, 'update_time', [])
        got = await SpaceListCache.get(7, 'update_time')
    assert got == []


@pytest.mark.asyncio
async def test_redis_unavailable_degrades_gracefully():
    with patch('bisheng.knowledge.domain.services.space_list_cache.get_redis_client',
               new_callable=AsyncMock, return_value=None):
        assert await SpaceListCache.get(7, 'update_time') is None
        await SpaceListCache.set(7, 'update_time', [])  # must not raise


def test_ttl_constant_is_15_seconds():
    assert SPACE_LIST_CACHE_TTL == 15
