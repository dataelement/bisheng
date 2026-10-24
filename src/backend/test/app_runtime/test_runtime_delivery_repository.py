"""F086 durable operations: real SQL transactions, no Engine or middleware."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.app_runtime.domain.models.runtime_delivery import (
    RUNTIME_TABLES,
    RuntimeCapacityReservation,
    RuntimeNode,
    RuntimeOperation,
)


@pytest.fixture
async def runtime_repo(monkeypatch):
    from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeDeliveryRepository
    from bisheng.core.context.tenant import current_tenant_id

    token = current_tenant_id.set(1)
    engine = create_async_engine("sqlite+aiosqlite://")

    # Disable sqlite3's legacy autocommit behavior so SAVEPOINT participates in
    # the outer transaction, as it does in the supported MySQL/DM8 databases.
    @event.listens_for(engine.sync_engine, "connect")
    def connect(connection, _record):
        connection.isolation_level = None

    @event.listens_for(engine.sync_engine, "begin")
    def begin(connection):
        connection.exec_driver_sql("BEGIN")

    from bisheng.app_runtime.domain.models.runtime_host_isolation import RuntimeHostIsolationReport
    from bisheng.app_runtime.domain.repositories.host_isolation_repository import REQUIRED
    from bisheng.common.services.config_service import settings

    monkeypatch.setattr(
        settings.app_runtime,
        "runtime_host_isolation_nodes",
        {"node-a": {"engine_id": "engine-a", "network_id": "network-a", "config_digest": "a" * 64}},
    )
    async with engine.begin() as conn:
        await conn.run_sync(RuntimeHostIsolationReport.__table__.create)
        for model in RUNTIME_TABLES:
            await conn.run_sync(model.__table__.create)

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    repo = RuntimeDeliveryRepository(sessions)
    await repo.save(
        RuntimeNode(
            id="node-a",
            engine_id="engine-a",
            platform="linux/arm64",
            memory_budget_mb=1024,
            cpu_budget_millicores=2000,
            heartbeat_at=datetime.utcnow(),
        )
    )
    # Other ledger tests assume a verified node. This synthetic evidence is
    # not a host-firewall test; test_host_isolation separately removes it.
    async with repo.transaction() as session:
        session.add(
            RuntimeHostIsolationReport(
                id="node-a",
                engine_id="engine-a",
                network_id="network-a",
                config_digest="a" * 64,
                rule_digest="b" * 64,
                revision=1,
                checked_at=datetime.utcnow(),
                valid_until=datetime.utcnow() + timedelta(seconds=60),
                status="valid",
                checks=dict.fromkeys(REQUIRED, True),
            )
        )
    yield repo
    await engine.dispose()
    current_tenant_id.reset(token)


def operation(key="request-1", app="app-a", digest="a" * 64):
    return RuntimeOperation(
        tenant_id=1,
        app_id=app,
        scope_key=f"1/{app}",
        idempotency_key=key,
        request_digest=digest,
        kind="deploy",
        node_id="node-a",
        deadline=datetime.utcnow() + timedelta(minutes=30),
    )


async def test_request_idempotency_and_digest_conflict(runtime_repo):
    """AC-36: response loss returns the same operation; changed input is rejected."""
    from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict

    first = await runtime_repo.create_operation(operation())
    assert (await runtime_repo.create_operation(operation())).id == first.id
    with pytest.raises(RuntimeConflict, match="idempotency"):
        await runtime_repo.create_operation(operation(digest="b" * 64))


async def test_capacity_reserved_once_and_unknown_stop_stays_counted(runtime_repo):
    """AC-34, AC-63: reservations precede changes and require confirmed stop to release."""
    from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict

    a = await runtime_repo.create_operation(operation())
    held = await runtime_repo.admit(a.id, memory_mb=768, cpu_millicores=1000)
    assert (await runtime_repo.admit(a.id, memory_mb=768, cpu_millicores=1000)).id == held.id
    b = await runtime_repo.create_operation(operation("request-2", "app-b"))
    with pytest.raises(RuntimeConflict, match="capacity"):
        await runtime_repo.admit(b.id, memory_mb=512, cpu_millicores=500)
    with pytest.raises(RuntimeConflict, match="stopped"):
        await runtime_repo.release(a.id, stopped=False)
    assert (await runtime_repo.get(RuntimeCapacityReservation, held.id)).state == "held"
    await runtime_repo.release(a.id, stopped=True)
    assert (await runtime_repo.admit(b.id, memory_mb=512, cpu_millicores=500)).state == "held"


async def test_assignment_rejects_competing_or_stale_executor(runtime_repo):
    """AC-35, AC-50: one durable owner, including across repository instances."""
    from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict

    a = await runtime_repo.create_operation(operation())
    claim = await runtime_repo.claim(a.id, node_id="node-a", generation=a.generation, owner_epoch=a.owner_epoch)
    assert claim.id == a.id
    b = await runtime_repo.create_operation(operation("request-2"))
    with pytest.raises(RuntimeConflict, match="owner"):
        await runtime_repo.claim(b.id, node_id="node-a", generation=b.generation, owner_epoch=b.owner_epoch)
    with pytest.raises(RuntimeConflict, match="fence"):
        await runtime_repo.claim(a.id, node_id="node-a", generation=999, owner_epoch=a.owner_epoch)


async def test_stale_node_cannot_admit_new_work(runtime_repo):
    """AC-34, AC-37: stale Engine observations cannot authorize a new write."""
    from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict

    node = await runtime_repo.get(RuntimeNode, "node-a")
    node.heartbeat_at = datetime.utcnow() - timedelta(minutes=5)
    await runtime_repo.save(node)
    a = await runtime_repo.create_operation(operation())
    with pytest.raises(RuntimeConflict, match="stale"):
        await runtime_repo.admit(a.id, memory_mb=1, cpu_millicores=1)


async def test_scope_and_write_validation(runtime_repo):
    """AC-06, AC-61: tenant mismatch is refused even before ORM hooks run."""
    from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
    from bisheng.core.context.tenant import current_tenant_id

    token = current_tenant_id.set(2)
    try:
        with pytest.raises(RuntimeConflict, match="tenant"):
            await runtime_repo.create_operation(operation())
    finally:
        current_tenant_id.reset(token)


async def test_late_unclaimed_operation_cannot_take_back_new_generation(runtime_repo):
    """AC-35: an older queued operation cannot overwrite a newer completed owner."""
    from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict

    old = await runtime_repo.create_operation(operation("old"))
    new_request = operation("new")
    new_request.generation = 2
    new = await runtime_repo.create_operation(new_request)
    await runtime_repo.claim(new.id, node_id="node-a", generation=2, owner_epoch=1)
    new.status = "completed"
    new.cleanup_status = "complete"
    await runtime_repo.save(new)
    with pytest.raises(RuntimeConflict, match="fence"):
        await runtime_repo.claim(old.id, node_id="node-a", generation=1, owner_epoch=1)


async def test_completed_fact_ack_can_be_retried_without_reexecution(runtime_repo):
    """AC-36: a lost terminal acknowledgement is safe to resend."""
    request = operation()
    request.kind = "prepare"
    op = await runtime_repo.create_operation(request)
    values = {
        "sequence": 1,
        "node_id": "node-a",
        "generation": 1,
        "owner_epoch": 1,
        "phase": "completed",
        "detail": {"stopped": True},
    }
    first = await runtime_repo.record_fact(op.id, **values)
    op.status = "completed"
    await runtime_repo.save(op)
    assert (await runtime_repo.record_fact(op.id, **values)).id == first.id


async def test_terminal_history_cannot_starve_node_plan(runtime_repo):
    """AC-35, AC-40: SQL filters history before enumerating actionable operations."""
    history = []
    for index in range(10001):
        row = operation(f"history-{index}")
        row.status, row.cleanup_status = "completed", "complete"
        history.append(row)
    current = operation("current-after-history")
    async with runtime_repo.transaction() as session:
        session.add_all([*history, current])
        await session.flush()
    assert [row.id for row in await runtime_repo.node_operations("node-a")] == [current.id]


async def test_caller_environment_never_enters_plaintext_operation_intent(runtime_repo):
    """AC-53: only the backend's sealing step can attach execution credentials."""
    from types import SimpleNamespace

    from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
    from bisheng.app_runtime.domain.schemas.runtime_delivery import OperationInput
    from bisheng.app_runtime.domain.services.runtime_operation_service import RuntimeOperationService

    async def load(app):
        return SimpleNamespace(id=app, tenant_id=1, state="draft")

    service = RuntimeOperationService(runtime_repo, app_loader=load)
    for key in ["sealed_env", "runtime_env", "build_env"]:
        with pytest.raises(RuntimeConflict, match="caller_environment"):
            await service.create(
                OperationInput(
                    app_id="app-a",
                    kind="stop",
                    idempotency_key=key,
                    node_id="node-a",
                    generation=1,
                    owner_epoch=1,
                    payload={key: {"TOKEN": "fixture-only"}},
                )
            )


async def test_failed_admission_does_not_leave_executable_intent(runtime_repo):
    """AC-35, AC-36: a capacity failure rolls back the enclosing operation transaction."""
    from types import SimpleNamespace

    from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
    from bisheng.app_runtime.domain.schemas.runtime_delivery import OperationInput
    from bisheng.app_runtime.domain.services.runtime_operation_service import RuntimeOperationService

    async def load(app):
        return SimpleNamespace(id=app, tenant_id=1, state="draft")

    service = RuntimeOperationService(runtime_repo, app_loader=load)
    with pytest.raises(RuntimeConflict, match="capacity_exhausted"):
        await service.create(
            OperationInput(
                app_id="app-a",
                kind="prepare",
                idempotency_key="too-large",
                node_id="node-a",
                generation=1,
                owner_epoch=1,
                payload={"tier": {"memory_mb": 2048}},
            )
        )
    assert await runtime_repo.find(RuntimeOperation, idempotency_key="too-large") == []
