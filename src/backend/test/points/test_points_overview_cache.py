"""运营概览缓存（AC-19：允许 5min 陈旧）。

三个指标均为 user_point_log / user_point_account 上的全历史聚合，耗时随流水量增长，
因此加 Redis 缓存；缓存故障必须退化为直查库而不是报错。
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.points.domain.services import points_query_service as mod
from bisheng.points.domain.services.points_query_service import PointsQueryService

ADMIN = SimpleNamespace(is_admin=lambda: True, is_global_super=True)


def _repo() -> SimpleNamespace:
    """返回带计数的假仓储，用于断言是否真的查了库。"""
    return SimpleNamespace(
        sum_total_issued=AsyncMock(return_value=100),
        sum_violation_deducted=AsyncMock(return_value=30),
        sum_tenant_earn=AsyncMock(return_value=42),
    )


@pytest.mark.asyncio
async def test_overview_caches_and_serves_second_call_from_cache():
    """首次查库并回写缓存，二次命中缓存后不再查库。"""
    repo = _repo()
    service = PointsQueryService(session=None, repository=repo, ledger=None)
    store: dict[str, dict] = {}

    async def fake_get(key):
        return store.get(key)

    async def fake_set(key, payload):
        store[key] = payload

    with (
        patch.object(PointsQueryService, "_overview_cache_get", staticmethod(fake_get)),
        patch.object(PointsQueryService, "_overview_cache_set", staticmethod(fake_set)),
    ):
        first = await service.overview(1, ADMIN)
        second = await service.overview(1, ADMIN)

    assert first.total_issued == 100
    assert first.total_balance == 70
    assert first.total_violation_deducted == 30
    assert first.total_issued_mom == 42
    assert second == first
    # 第二次必须来自缓存：三个聚合各自只被调用一次。
    assert repo.sum_total_issued.await_count == 1
    assert repo.sum_violation_deducted.await_count == 1
    assert repo.sum_tenant_earn.await_count == 1
    assert store[f"{mod.OVERVIEW_CACHE_PREFIX}1"]["total_issued"] == 100
    assert store[f"{mod.OVERVIEW_CACHE_PREFIX}1"]["total_issued_mom"] == 42


@pytest.mark.asyncio
async def test_overview_cache_is_scoped_per_tenant():
    """不同租户不能串用同一份概览缓存。"""
    repo = _repo()
    service = PointsQueryService(session=None, repository=repo, ledger=None)
    store: dict[str, dict] = {}

    async def fake_get(key):
        return store.get(key)

    async def fake_set(key, payload):
        store[key] = payload

    with (
        patch.object(PointsQueryService, "_overview_cache_get", staticmethod(fake_get)),
        patch.object(PointsQueryService, "_overview_cache_set", staticmethod(fake_set)),
    ):
        await service.overview(1, ADMIN)
        await service.overview(2, ADMIN)

    assert set(store) == {f"{mod.OVERVIEW_CACHE_PREFIX}1", f"{mod.OVERVIEW_CACHE_PREFIX}2"}
    assert repo.sum_total_issued.await_count == 2
    assert repo.sum_tenant_earn.await_count == 2


@pytest.mark.asyncio
async def test_overview_falls_back_to_db_when_redis_unavailable(caplog):
    """Redis 不可用时概览仍可返回，不向上抛错。"""
    import importlib

    redis_manager_module = importlib.import_module("bisheng.core.cache.redis_manager")

    repo = _repo()
    service = PointsQueryService(session=None, repository=repo, ledger=None)
    client = AsyncMock(side_effect=RuntimeError("redis down"))

    with patch.object(redis_manager_module, "get_redis_client", client):
        with caplog.at_level("WARNING", logger=mod.__name__):
            out = await service.overview(1, ADMIN)

    assert out.total_issued == 100
    assert out.total_balance == 70
    assert out.total_issued_mom == 42
    assert repo.sum_total_issued.await_count == 1
    assert repo.sum_tenant_earn.await_count == 1
    # 读、写各降级一次，确认真的进了异常分支而非碰巧命中。
    assert client.await_count == 2
    assert sum("cache" in r.message for r in caplog.records) == 2


@pytest.mark.asyncio
async def test_overview_requires_platform_admin():
    """非管理员不得读运营概览。"""
    repo = _repo()
    service = PointsQueryService(session=None, repository=repo, ledger=None)
    with pytest.raises(Exception):
        await service.overview(1, SimpleNamespace(is_admin=lambda: False, is_global_super=False))
    assert repo.sum_total_issued.await_count == 0
