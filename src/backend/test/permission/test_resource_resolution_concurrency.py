"""Business target loading shares a connection budget across concurrent requests."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool

from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.permission.application import business_authorization as business
from bisheng.permission.application.resource_authorization import ResourceAuthorizationRegistry
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.permission_action_service import PermissionActor


class _LoadingPort:
    def __init__(self):
        self.active = 0
        self.peak = 0
        self.completed = 0

    async def resolve_permission_target(self, *, resource_id, actor, action):
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            # Model a checked-out connection without needing external middleware.
            await asyncio.sleep(0.001)
            return VerifiedPermissionTarget.from_business_service(
                tenant_id=actor.tenant_id,
                resource_type="knowledge_file",
                resource_id=resource_id,
                resource_version=1,
                context_version="v1",
            )
        finally:
            self.active -= 1
            self.completed += 1


@pytest.mark.parametrize("method", ["batch_check_business_actions", "batch_check_business_visible"])
async def test_large_batch_limits_business_loads(monkeypatch, method):
    port = _LoadingPort()
    registry = ResourceAuthorizationRegistry()
    registry.register("knowledge_file", port)
    batch_sizes = []

    async def decide(actor, targets, action):
        batch_sizes.append(len(targets))
        return tuple(True for _ in targets)

    monkeypatch.setattr(business, "get_f048_resource_registry", AsyncMock(return_value=registry))
    monkeypatch.setattr(
        business, "get_f048_runtime", AsyncMock(return_value=SimpleNamespace(batch_check_actions=decide))
    )
    kwargs = {"actions": ("visible",)} if method == "batch_check_business_actions" else {}
    result = await asyncio.wait_for(
        getattr(business, method)(
            SimpleNamespace(user_id=7, tenant_id=1, is_global_super=False),
            resource_type="knowledge_file",
            resource_ids=range(1, 1001),
            **kwargs,
        ),
        timeout=10,
    )

    assert len(result) == 1000
    assert all(result.values())
    assert 1 < port.peak <= 20
    assert port.completed == 1000
    assert batch_sizes == [100] * 10


async def test_simultaneous_batch_and_single_requests_share_the_budget(monkeypatch):
    port = _LoadingPort()
    # Even independently composed registries on the same loop share the limit.
    registries = [ResourceAuthorizationRegistry() for _ in range(2)]
    for registry in registries:
        registry.register("knowledge_file", port)
    monkeypatch.setattr(business, "get_f048_resource_registry", AsyncMock(return_value=registries[0]))
    monkeypatch.setattr(
        business,
        "get_f048_runtime",
        AsyncMock(
            return_value=SimpleNamespace(batch_check_actions=AsyncMock(side_effect=lambda a, ts, act: [True] * len(ts)))
        ),
    )
    login = SimpleNamespace(user_id=7, tenant_id=1, is_global_super=False)
    actor = PermissionActor(user_id=7, current_tenant_id=1)
    requests = (
        [
            business.batch_check_business_actions(
                login, resource_type="knowledge_file", resource_ids=range(1, 201), actions=("visible", "edit")
            )
            for _ in range(3)
        ]
        + [
            business.batch_check_business_visible(login, resource_type="knowledge_file", resource_ids=range(1, 201))
            for _ in range(3)
        ]
        + [
            registries[1].resolve(resource_type="knowledge_file", resource_id=str(index), actor=actor, action="visible")
            for index in range(1, 41)
        ]
    )
    results = await asyncio.wait_for(asyncio.gather(*requests), timeout=10)

    assert all(results)
    assert 1 < port.peak <= 20
    assert port.completed == 1840
    assert port.active == 0


async def test_concurrent_requests_complete_with_a_finite_sqlalchemy_pool(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=AsyncAdaptedQueuePool,
        pool_size=20,
        max_overflow=0,
        pool_timeout=0.05,
    )
    peak_connections = 0

    class DatabasePort:
        async def resolve_permission_target(self, *, resource_id, actor, action):
            nonlocal peak_connections
            async with engine.connect() as connection:
                peak_connections = max(peak_connections, engine.pool.checkedout())
                await connection.execute(text("SELECT 1"))
                # Hold connections long enough that an unbounded burst times out.
                await asyncio.sleep(0.01)
            return VerifiedPermissionTarget.from_business_service(
                tenant_id=actor.tenant_id,
                resource_type="knowledge_file",
                resource_id=resource_id,
                resource_version=1,
                context_version="v1",
            )

    registry = ResourceAuthorizationRegistry()
    registry.register("knowledge_file", DatabasePort())
    monkeypatch.setattr(business, "get_f048_resource_registry", AsyncMock(return_value=registry))
    monkeypatch.setattr(
        business,
        "get_f048_runtime",
        AsyncMock(
            return_value=SimpleNamespace(
                batch_check_actions=AsyncMock(side_effect=lambda actor, targets, action: [True] * len(targets))
            )
        ),
    )
    login = SimpleNamespace(user_id=7, tenant_id=1, is_global_super=False)
    try:
        results = await asyncio.wait_for(
            asyncio.gather(
                *(
                    business.batch_check_business_visible(
                        login, resource_type="knowledge_file", resource_ids=range(1, 101)
                    )
                    for _ in range(4)
                ),
                return_exceptions=True,
            ),
            timeout=10,
        )
        assert not [result for result in results if isinstance(result, BaseException)]
        assert all(len(result) == 100 and all(result.values()) for result in results)
        assert 1 < peak_connections <= 20
        assert engine.pool.checkedout() == 0
    finally:
        await engine.dispose()


async def test_cancellation_and_failures_release_resolution_slots():
    entered = 0
    saturated = asyncio.Event()
    release = asyncio.Event()
    actor = PermissionActor(user_id=7, current_tenant_id=1)

    class BlockingPort:
        async def resolve_permission_target(self, **kwargs):
            nonlocal entered
            entered += 1
            if entered == 20:
                saturated.set()
            await release.wait()
            raise PermissionInvalidResourceError()

    registry = ResourceAuthorizationRegistry()
    registry.register("knowledge_file", BlockingPort())

    def resolve(index):
        return registry.resolve(resource_type="knowledge_file", resource_id=str(index), actor=actor, action="visible")

    tasks = [asyncio.create_task(resolve(index)) for index in range(1, 42)]
    try:
        await asyncio.wait_for(saturated.wait(), timeout=5)
        tasks[0].cancel()
        tasks[-1].cancel()
        release.set()
        outcomes = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=5)
        assert sum(isinstance(result, asyncio.CancelledError) for result in outcomes) == 2
        assert all(isinstance(result, (asyncio.CancelledError, PermissionInvalidResourceError)) for result in outcomes)

        port = _LoadingPort()
        next_registry = ResourceAuthorizationRegistry()
        next_registry.register("knowledge_file", port)
        await asyncio.wait_for(
            asyncio.gather(
                *(
                    next_registry.resolve(
                        resource_type="knowledge_file", resource_id=str(index), actor=actor, action="visible"
                    )
                    for index in range(1, 41)
                )
            ),
            timeout=5,
        )
        assert port.peak == 20
        assert port.completed == 40
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_sync_callers_can_use_successive_event_loops():
    registry = ResourceAuthorizationRegistry()
    port = _LoadingPort()
    registry.register("knowledge_file", port)
    actor = PermissionActor(user_id=7, current_tenant_id=1)

    async def run_batch():
        return await asyncio.gather(
            *(
                registry.resolve(resource_type="knowledge_file", resource_id=str(index), actor=actor, action="visible")
                for index in range(1, 41)
            )
        )

    for _ in range(2):
        result = await asyncio.wait_for(asyncio.to_thread(lambda: asyncio.run(run_batch())), timeout=5)
        assert len(result) == 40
    assert port.completed == 80
    assert port.peak == 20
