"""Opt-in F086 SQL concurrency checks against a disposable MySQL/DM8 schema.

F086_TEST_DATABASE_URL must name an e2e_f086_* schema/database. The caller
creates that empty database; this fixture only creates/drops F086 tables.
No Engine, Redis, MinIO, authorization or deployed API behavior is covered.
"""

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.app_runtime.domain.models.runtime_delivery import (
    RUNTIME_TABLES,
    RuntimeAssignment,
    RuntimeCapacityReservation,
    RuntimeNode,
    RuntimeOperation,
)
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import (
    RuntimeConflict,
    RuntimeDeliveryRepository,
)
from bisheng.core.context.tenant import current_tenant_id

pytestmark = pytest.mark.skipif(
    not os.environ.get("F086_TEST_DATABASE_URL"),
    reason="requires disposable live SQL database",
)


@pytest.fixture
async def live_repo():
    url = make_url(os.environ["F086_TEST_DATABASE_URL"])
    namespace = url.query.get("schema") or url.database or ""
    assert namespace.lower().startswith("e2e_f086_"), "refusing non-test SQL namespace"
    assert os.environ.get("F086_TEST_DATABASE_ALLOW_CREATE") == "1"
    engine = create_async_engine(url, pool_size=12, max_overflow=0, echo=False)
    token = current_tenant_id.set(1)
    async with engine.begin() as connection:
        for model in RUNTIME_TABLES:
            await connection.run_sync(model.__table__.create)

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    repo = RuntimeDeliveryRepository(sessions)
    await repo.save(
        RuntimeNode(
            id="node-a",
            engine_id="live-test",
            platform="linux/amd64",
            memory_budget_mb=1024,
            cpu_budget_millicores=2000,
            heartbeat_at=datetime.utcnow(),
        )
    )
    try:
        yield repo
    finally:
        async with engine.begin() as connection:
            for model in reversed(RUNTIME_TABLES):
                await connection.run_sync(model.__table__.drop)
        await engine.dispose()
        current_tenant_id.reset(token)


def request(key, app="app-a", tenant=1):
    return RuntimeOperation(
        tenant_id=tenant,
        app_id=app,
        scope_key=f"{tenant}/{app}",
        idempotency_key=key,
        request_digest="a" * 64,
        kind="deploy",
        node_id="node-a",
        deadline=datetime.utcnow() + timedelta(minutes=5),
    )


async def test_live_identical_concurrent_requests_return_one_operation(live_repo, monkeypatch):
    # Force all workers to observe the same pre-insert state on distinct connections.
    barrier = asyncio.Barrier(12)
    seen = set()
    original_find = live_repo.find

    async def synchronized_find(model, **fields):
        rows = await original_find(model, **fields)
        task = asyncio.current_task()
        if model is RuntimeOperation and fields.get("idempotency_key") == "same" and task not in seen:
            seen.add(task)
            await asyncio.wait_for(barrier.wait(), timeout=30)
        return rows

    monkeypatch.setattr(live_repo, "find", synchronized_find)
    results = await asyncio.gather(
        *(live_repo.create_operation(request("same")) for _ in range(12)),
        return_exceptions=True,
    )
    assert not [type(row).__name__ for row in results if isinstance(row, BaseException)]
    assert len({row.id for row in results}) == 1
    assert len(await live_repo.find(RuntimeOperation)) == 1


async def test_live_last_capacity_admits_only_one_tenant(live_repo):
    async def create_and_admit(tenant):
        token = current_tenant_id.set(tenant)
        try:
            op = await live_repo.create_operation(request(str(tenant), f"app-{tenant}", tenant))
            return await live_repo.admit(op.id, memory_mb=768, cpu_millicores=1000)
        finally:
            current_tenant_id.reset(token)

    results = await asyncio.gather(create_and_admit(1), create_and_admit(2), return_exceptions=True)
    assert len([row for row in results if isinstance(row, RuntimeCapacityReservation)]) == 1
    assert len([row for row in results if isinstance(row, RuntimeConflict) and str(row) == "capacity_exhausted"]) == 1
    assert (await live_repo.capacity_snapshot("node-a"))["committed_mb"] == 768


async def test_live_competing_claims_have_one_assignment(live_repo, monkeypatch):
    ops = [await live_repo.create_operation(request(f"claim-{i}")) for i in range(2)]
    barrier = asyncio.Barrier(2)
    original_get = live_repo.get

    async def synchronized_get(model, ident, **kwargs):
        row = await original_get(model, ident, **kwargs)
        if model is RuntimeOperation and kwargs.get("lock"):
            await asyncio.wait_for(barrier.wait(), timeout=30)
        return row

    monkeypatch.setattr(live_repo, "get", synchronized_get)
    results = await asyncio.gather(
        *(live_repo.claim(op.id, node_id="node-a", generation=1, owner_epoch=1) for op in ops),
        return_exceptions=True,
    )
    assert len([row for row in results if isinstance(row, RuntimeOperation)]) == 1
    assert len([row for row in results if isinstance(row, RuntimeConflict)]) == 1
    assignments = await live_repo.find(RuntimeAssignment, app_id="app-a")
    assert len(assignments) == 1
    assert assignments[0].active_operation_id in {op.id for op in ops}


async def test_live_outer_rollback_removes_nested_operation_and_reservation(live_repo):
    with pytest.raises(RuntimeError, match="simulated business commit failure"):
        async with live_repo.transaction():
            op = await live_repo.create_operation(request("rollback"))
            await live_repo.admit(op.id, memory_mb=128, cpu_millicores=100)
            raise RuntimeError("simulated business commit failure")
    assert not await live_repo.find(RuntimeOperation)
    assert not await live_repo.find(RuntimeCapacityReservation)


async def test_live_foreign_tenant_cannot_load_or_write_operation(live_repo):
    op = await live_repo.create_operation(request("private"))
    token = current_tenant_id.set(2)
    try:
        with pytest.raises(RuntimeConflict, match="tenant_scope_mismatch"):
            await live_repo.get(RuntimeOperation, op.id)
        with pytest.raises(RuntimeConflict, match="tenant_scope_mismatch"):
            await live_repo.create_operation(request("forged"))
    finally:
        current_tenant_id.reset(token)
