"""合并扫描必须保留并发租户隔离、全局预算和续扫公平性。"""

import asyncio
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.core.context.tenant import (
    current_tenant_id,
    get_current_tenant_id,
    get_visible_tenant_ids,
    is_strict_tenant_filter,
)
from test.knowledge.projection_scan_helpers import MemoryRedis
from test.knowledge.test_knowledge_document_permission_reconcile_worker import projection_worker  # noqa: F401


@pytest.fixture
def runner(monkeypatch):
    scanner = importlib.import_module("bisheng.worker.knowledge._projection_scan")
    redis = MemoryRedis()
    conf = SimpleNamespace(projection_scan_total_time_budget_seconds=10, projection_scan_tenant_concurrency=2)

    async def create(tenant_id):
        return scanner.ProjectionScanState(redis, tenant_id)

    monkeypatch.setattr(scanner.ProjectionScanState, "create", create)
    monkeypatch.setattr(scanner, "get_shared_storage_conf", lambda: conf)
    monkeypatch.setattr(scanner.TenantDao, "aget_children_ids_active", AsyncMock(return_value=[2, 3, 4]))
    return scanner, redis, conf


async def test_parallel_tenants_have_isolated_context_and_failures(runner, monkeypatch):
    scanner, redis, conf = runner
    initial_tenant = get_current_tenant_id()
    initial_visible = get_visible_tenant_ids()
    initial_strict = is_strict_tenant_filter()
    contexts = []
    active = peak = 0
    ready = asyncio.Event()

    async def scan(tenant_id):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if active == 2:
            ready.set()
        try:
            await ready.wait()
            contexts.append((tenant_id, get_current_tenant_id(), get_visible_tenant_ids(), is_strict_tenant_filter()))
            assert await asyncio.to_thread(get_current_tenant_id) == tenant_id
            if tenant_id == 2:
                raise RuntimeError("tenant 2 database failure")
            return tenant_id
        finally:
            active -= 1

    monkeypatch.setattr(scanner, "scan_tenant", scan)
    root_state = await scanner.ProjectionScanState.create(1)
    await root_state.save_cursor({"projection": 777})
    result = await scanner.scan_documents()
    assert result == {
        "status": "completed_with_failures",
        "tenants_visited": 4,
        "projection_dispatched": 8,
        "failed_tenants": [2],
    }
    assert sorted(contexts) == [(i, i, frozenset({i}), True) for i in range(1, 5)]
    assert peak == conf.projection_scan_tenant_concurrency
    assert (get_current_tenant_id(), get_visible_tenant_ids(), is_strict_tenant_filter()) == (
        initial_tenant,
        initial_visible,
        initial_strict,
    )
    assert await root_state.cursor() == {"projection": 777}
    assert not redis.locks


async def test_global_budget_resumes_at_next_tenant(runner, monkeypatch):
    scanner, redis, conf = runner
    conf.projection_scan_total_time_budget_seconds = 1
    conf.projection_scan_tenant_concurrency = 1
    visited = []

    async def slow(tenant_id):
        visited.append(tenant_id)
        await asyncio.sleep(10)

    monkeypatch.setattr(scanner, "scan_tenant", slow)
    result = await scanner.scan_documents()
    assert result["status"] == "budget_reached"
    assert visited == [1]
    assert not redis.locks

    async def fast(tenant_id):
        visited.append(tenant_id)
        return 0

    visited.clear()
    monkeypatch.setattr(scanner, "scan_tenant", fast)
    assert (await scanner.scan_documents())["status"] == "completed"
    assert visited == [2, 3, 4, 1]


async def test_global_lock_skips_duplicate_scan(runner):
    scanner, redis, _ = runner
    state = await scanner.ProjectionScanState.create(1)
    redis.locks.add(state.key("lock", "all_tenants"))
    assert (await scanner.scan_documents())["status"] == "already_running"
    scanner.TenantDao.aget_children_ids_active.assert_not_awaited()


async def test_targeted_scan_does_not_enumerate_tenants_and_restores_context(runner, monkeypatch):
    scanner, _, _ = runner
    token = current_tenant_id.set(7)

    async def scan(tenant_id):
        assert tenant_id == get_current_tenant_id() == 7
        return 300

    monkeypatch.setattr(scanner, "scan_tenant", scan)
    try:
        assert (await scanner.scan_documents(7))["projection_dispatched"] == 300
        assert get_current_tenant_id() == 7
        scanner.TenantDao.aget_children_ids_active.assert_not_awaited()
    finally:
        current_tenant_id.reset(token)
