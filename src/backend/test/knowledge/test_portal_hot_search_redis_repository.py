import pytest

from bisheng.core.context.tenant import set_current_tenant_id
from bisheng.knowledge.domain.repositories.implementations.portal_hot_search_redis_repository_impl import (
    PortalHotSearchRedisRepositoryImpl,
)
from bisheng.knowledge.domain.schemas.portal_hot_search_schema import PortalHotSearchItem


class _FakeConn:
    def __init__(self):
        self.store = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        self.store.pop(key, None)


class _FakeRedisClient:
    def __init__(self):
        self.async_connection = _FakeConn()


@pytest.fixture(autouse=True)
def _tenant():
    set_current_tenant_id(1)
    yield
    set_current_tenant_id(None)


async def test_replace_and_get_roundtrip():
    repo = PortalHotSearchRedisRepositoryImpl(redis_client=_FakeRedisClient())
    items = [
        PortalHotSearchItem(rank=1, query="设备检修安全要求？"),
        PortalHotSearchItem(rank=2, query="能源管理制度？"),
    ]
    await repo.replace(1, items)
    got = await repo.get(1)
    assert [i.query for i in got] == ["设备检修安全要求？", "能源管理制度？"]


async def test_get_returns_none_on_miss():
    repo = PortalHotSearchRedisRepositoryImpl(redis_client=_FakeRedisClient())
    assert await repo.get(1) is None


async def test_lock_is_exclusive_until_released():
    client = _FakeRedisClient()
    repo = PortalHotSearchRedisRepositoryImpl(redis_client=client)
    assert await repo.acquire_lock(1) is True
    # second acquisition fails while held
    assert await repo.acquire_lock(1) is False
    await repo.release_lock(1)
    assert await repo.acquire_lock(1) is True
