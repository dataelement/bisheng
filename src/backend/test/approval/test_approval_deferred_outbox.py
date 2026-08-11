from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_instance import (
    ApprovalException,
    ApprovalInstance,
    ApprovalInstanceStatus,
    ApprovalOutbox,
    ApprovalOutboxStatus,
)
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.approval.domain.services.approval_outbox_service import (
    ApprovalOutboxService,
    Completed,
    Deferred,
)
from bisheng.core.context.tenant import current_tenant_id


@pytest_asyncio.fixture
async def deferred_db(monkeypatch: pytest.MonkeyPatch):
    tenant_token = current_tenant_id.set(42)
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [ApprovalInstance.__table__, ApprovalOutbox.__table__, ApprovalException.__table__]
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: SQLModel.metadata.create_all(sync_conn, tables=tables))

    @asynccontextmanager
    async def factory():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(
        "bisheng.approval.domain.repositories.approval_instance_repository.get_async_db_session",
        factory,
    )
    try:
        yield
    finally:
        await engine.dispose()
        current_tenant_id.reset(tenant_token)


async def _seed_bundle(
    *,
    instance_status: str = ApprovalInstanceStatus.EXECUTING,
    outbox_status: str = ApprovalOutboxStatus.PROCESSING,
) -> tuple[ApprovalInstance, ApprovalOutbox]:
    instance = await ApprovalInstanceRepository.create_instance(
        ApprovalInstance(
            tenant_id=42,
            scenario_code="knowledge_space_file_change",
            scenario_name="knowledge-space-file-change",
            handler_key="knowledge_space_file_change",
            business_key="file-change:88",
            business_resource_type="knowledge_space_file_change",
            business_resource_id="88",
            business_name="rename report.pdf",
            applicant_user_id=7,
            applicant_user_name="applicant",
            status=instance_status,
            payload_snapshot={"request_id": 88},
            detail_snapshot={},
        )
    )
    outbox = await ApprovalInstanceRepository.create_outbox(
        ApprovalOutbox(
            tenant_id=42,
            instance_id=instance.id,
            handler_key="knowledge_space_file_change",
            status=outbox_status,
            payload_snapshot={"request_id": 88},
        )
    )
    return instance, outbox


async def _load_bundle(instance_id: int, outbox_id: int) -> tuple[ApprovalInstance, ApprovalOutbox]:
    async with ApprovalInstanceRepository.decision_session() as session:
        return await session.get(ApprovalInstance, instance_id), await session.get(ApprovalOutbox, outbox_id)


async def test_ordinary_claim_never_reclaims_deferred_even_after_processing_ttl():
    now = datetime.utcnow()
    outbox = ApprovalOutbox(
        id=1,
        tenant_id=42,
        instance_id=1,
        handler_key="knowledge_space_file_change",
        status=ApprovalOutboxStatus.DEFERRED,
        execution_token="generation-1",
        deferred_deadline=now - timedelta(hours=1),
        heartbeat_at=now - timedelta(hours=1),
        update_time=now - timedelta(days=1),
    )

    class ClaimRepo:
        async def get_outbox(self, _outbox_id):
            return outbox

        async def claim_outbox(self, **_kwargs):
            raise AssertionError("deferred must be rejected before ordinary claim")

    executor = AsyncMock()
    service = ApprovalOutboxService(instance_repository=ClaimRepo())

    assert await service.execute_outbox(outbox_id=1, executor=executor) is False
    executor.assert_not_awaited()


async def test_completed_and_legacy_result_keep_old_synchronous_behavior():
    assert Completed().success is True
    assert ApprovalOutboxService.normalize_execution_result(None) == (True, None)
    assert ApprovalOutboxService.normalize_execution_result({"status": "ok"}) == (True, None)
    assert ApprovalOutboxService.normalize_execution_result(Completed()) == (True, None)
    assert ApprovalOutboxService.normalize_execution_result((False, "boom")) == (False, "boom")


async def test_execute_outbox_persists_deferred_result_instead_of_finalizing(deferred_db):
    instance, outbox = await _seed_bundle(
        instance_status=ApprovalInstanceStatus.APPROVED,
        outbox_status=ApprovalOutboxStatus.PENDING,
    )
    deadline = datetime.utcnow() + timedelta(hours=1)
    service = ApprovalOutboxService(instance_repository=ApprovalInstanceRepository)

    assert await service.execute_outbox(
        outbox_id=outbox.id,
        executor=lambda _claimed: Deferred("generation-1", deadline),
    )

    saved_instance, saved_outbox = await _load_bundle(instance.id, outbox.id)
    assert saved_instance.status == ApprovalInstanceStatus.EXECUTING
    assert saved_outbox.status == ApprovalOutboxStatus.DEFERRED
    assert saved_outbox.execution_token == "generation-1"


async def test_defer_heartbeat_and_complete_validate_identity_token_and_lock_order(deferred_db, monkeypatch):
    instance, outbox = await _seed_bundle()
    now = datetime.utcnow().replace(microsecond=0)
    deadline = now + timedelta(minutes=30)
    service = ApprovalOutboxService(instance_repository=ApprovalInstanceRepository)
    order: list[str] = []
    original_instance_lock = service._lock_instance
    original_outbox_lock = service._lock_outbox

    async def instance_lock(*args, **kwargs):
        order.append("instance")
        return await original_instance_lock(*args, **kwargs)

    async def outbox_lock(*args, **kwargs):
        order.append("outbox")
        return await original_outbox_lock(*args, **kwargs)

    monkeypatch.setattr(service, "_lock_instance", instance_lock)
    monkeypatch.setattr(service, "_lock_outbox", outbox_lock)

    assert await service.defer_execution(
        tenant_id=42,
        instance_id=instance.id,
        outbox_id=outbox.id,
        result=Deferred("generation-1", deadline),
        now=now,
    )
    assert order == ["instance", "outbox"]

    assert not await service.heartbeat_deferred_execution(
        tenant_id=42,
        instance_id=instance.id,
        outbox_id=outbox.id,
        execution_token="old-generation",
        now=now + timedelta(seconds=1),
    )
    assert not await service.heartbeat_deferred_execution(
        tenant_id=7,
        instance_id=instance.id,
        outbox_id=outbox.id,
        execution_token="generation-1",
        now=now + timedelta(seconds=1),
    )
    assert await service.heartbeat_deferred_execution(
        tenant_id=42,
        instance_id=instance.id,
        outbox_id=outbox.id,
        execution_token="generation-1",
        now=now + timedelta(seconds=2),
    )
    assert await service.complete_deferred_execution(
        tenant_id=42,
        instance_id=instance.id,
        outbox_id=outbox.id,
        execution_token="generation-1",
    )
    assert not await service.complete_deferred_execution(
        tenant_id=42,
        instance_id=instance.id,
        outbox_id=outbox.id,
        execution_token="generation-1",
    )

    saved_instance, saved_outbox = await _load_bundle(instance.id, outbox.id)
    assert saved_instance.status == ApprovalInstanceStatus.EXECUTED
    assert saved_outbox.status == ApprovalOutboxStatus.SUCCESS
    assert saved_outbox.execution_token == "generation-1"
    assert saved_outbox.heartbeat_at == now + timedelta(seconds=2)


async def test_watchdog_only_fails_after_deadline_or_heartbeat_timeout(deferred_db):
    instance, outbox = await _seed_bundle()
    now = datetime.utcnow().replace(microsecond=0)
    service = ApprovalOutboxService(instance_repository=ApprovalInstanceRepository)
    assert await service.defer_execution(
        tenant_id=42,
        instance_id=instance.id,
        outbox_id=outbox.id,
        result=Deferred("generation-1", now + timedelta(minutes=10)),
        now=now,
    )

    assert not await service.fail_deferred_execution(
        tenant_id=42,
        instance_id=instance.id,
        outbox_id=outbox.id,
        execution_token="generation-1",
        error_summary="not expired",
        watchdog=True,
        heartbeat_timeout_seconds=120,
        now=now + timedelta(seconds=119),
    )
    assert await service.fail_deferred_execution(
        tenant_id=42,
        instance_id=instance.id,
        outbox_id=outbox.id,
        execution_token="generation-1",
        error_summary="heartbeat timeout",
        watchdog=True,
        heartbeat_timeout_seconds=120,
        now=now + timedelta(seconds=120),
    )

    saved_instance, saved_outbox = await _load_bundle(instance.id, outbox.id)
    assert saved_instance.status == ApprovalInstanceStatus.EXECUTE_FAILED
    assert saved_outbox.status == ApprovalOutboxStatus.FAILED
    assert saved_outbox.retry_count == 1

    # The non-null token is a durable deferred-origin marker. Even though the
    # status is FAILED, ordinary execution/retry must not rerun the handler and
    # bypass prepare_resume's atomic restoration of business steps.
    ordinary_executor = AsyncMock()
    assert not await service.execute_outbox(outbox_id=outbox.id, executor=ordinary_executor)
    assert not await service.retry_outbox(outbox_id=outbox.id, executor=ordinary_executor)
    ordinary_executor.assert_not_awaited()

    class Handler:
        async def prepare_resume(self, _session, new_token):
            return Deferred(new_token, now + timedelta(hours=1))

    new_token = await service.resume_deferred_execution(
        tenant_id=42,
        instance_id=instance.id,
        outbox_id=outbox.id,
        handler=Handler(),
    )
    assert new_token and new_token != "generation-1"
    assert not await service.complete_deferred_execution(
        tenant_id=42,
        instance_id=instance.id,
        outbox_id=outbox.id,
        execution_token="generation-1",
    )


async def test_deadline_boundary_is_expired_even_with_recent_heartbeat(deferred_db):
    instance, outbox = await _seed_bundle()
    now = datetime.utcnow().replace(microsecond=0)
    service = ApprovalOutboxService(instance_repository=ApprovalInstanceRepository)
    assert await service.defer_execution(
        tenant_id=42,
        instance_id=instance.id,
        outbox_id=outbox.id,
        result=Deferred("generation-1", now),
        now=now,
    )

    assert await service.fail_deferred_execution(
        tenant_id=42,
        instance_id=instance.id,
        outbox_id=outbox.id,
        execution_token="generation-1",
        error_summary="deadline reached",
        watchdog=True,
        heartbeat_timeout_seconds=3600,
        now=now,
    )


async def test_direct_failure_validates_token_and_is_idempotent(deferred_db):
    instance, outbox = await _seed_bundle()
    now = datetime.utcnow().replace(microsecond=0)
    service = ApprovalOutboxService(instance_repository=ApprovalInstanceRepository)
    assert await service.defer_execution(
        tenant_id=42,
        instance_id=instance.id,
        outbox_id=outbox.id,
        result=Deferred("generation-1", now + timedelta(hours=1)),
        now=now,
    )

    assert not await service.fail_deferred_execution(
        tenant_id=42,
        instance_id=instance.id,
        outbox_id=outbox.id,
        execution_token="old-generation",
        error_summary="late failure",
    )
    assert await service.fail_deferred_execution(
        tenant_id=42,
        instance_id=instance.id,
        outbox_id=outbox.id,
        execution_token="generation-1",
        error_summary="parse failed",
    )
    assert not await service.fail_deferred_execution(
        tenant_id=42,
        instance_id=instance.id,
        outbox_id=outbox.id,
        execution_token="generation-1",
        error_summary="duplicate",
    )


async def test_concurrent_duplicate_completion_is_terminal_and_side_effect_safe(deferred_db):
    instance, outbox = await _seed_bundle()
    now = datetime.utcnow().replace(microsecond=0)
    service = ApprovalOutboxService(instance_repository=ApprovalInstanceRepository)
    assert await service.defer_execution(
        tenant_id=42,
        instance_id=instance.id,
        outbox_id=outbox.id,
        result=Deferred("generation-1", now + timedelta(hours=1)),
        now=now,
    )

    results = await asyncio.gather(
        *(
            service.complete_deferred_execution(
                tenant_id=42,
                instance_id=instance.id,
                outbox_id=outbox.id,
                execution_token="generation-1",
            )
            for _ in range(2)
        )
    )

    assert any(results)
    saved_instance, saved_outbox = await _load_bundle(instance.id, outbox.id)
    assert saved_instance.status == ApprovalInstanceStatus.EXECUTED
    assert saved_outbox.status == ApprovalOutboxStatus.SUCCESS


async def test_resume_atomically_restores_business_and_approval_then_dispatches_post_commit(deferred_db):
    instance, outbox = await _seed_bundle(
        instance_status=ApprovalInstanceStatus.EXECUTE_FAILED,
        outbox_status=ApprovalOutboxStatus.FAILED,
    )
    old_token = "generation-1"
    outbox.execution_token = old_token
    outbox.deferred_deadline = datetime.utcnow() - timedelta(minutes=1)
    await ApprovalInstanceRepository.update_outbox(outbox)
    await ApprovalInstanceRepository.create_exception(
        ApprovalException(
            tenant_id=42,
            instance_id=instance.id,
            exception_type="execute_failed",
            status="open",
            detail={"error_summary": "parse failed"},
        )
    )
    service = ApprovalOutboxService(instance_repository=ApprovalInstanceRepository)
    prepare_observations: list[tuple[str, str]] = []
    bind_observations: list[tuple[int, int]] = []
    dispatch_observations: list[tuple[str, str, bool]] = []

    class Handler:
        def bind_deferred_execution(self, *, instance, outbox):
            bind_observations.append((instance.id, outbox.instance_id))

        async def prepare_resume(self, session, new_token):
            locked_instance = await session.get(ApprovalInstance, instance.id)
            locked_outbox = await session.get(ApprovalOutbox, outbox.id)
            prepare_observations.append((locked_instance.status, locked_outbox.status))
            locked_outbox.payload_snapshot = {"request_id": 88, "prepared_token": new_token}
            session.add(locked_outbox)
            return Deferred(new_token, datetime.utcnow() + timedelta(hours=1))

    async def dispatch(outbox_id, execution_token):
        saved_instance, saved_outbox = await _load_bundle(instance.id, outbox.id)
        dispatch_observations.append(
            (saved_instance.status, saved_outbox.status, saved_outbox.execution_token == execution_token)
        )

    new_token = await service.resume_deferred_execution(
        tenant_id=42,
        instance_id=instance.id,
        outbox_id=outbox.id,
        handler=Handler(),
        post_commit_dispatch=dispatch,
    )

    assert new_token and new_token != old_token
    assert bind_observations == [(instance.id, instance.id)]
    assert prepare_observations == [(ApprovalInstanceStatus.EXECUTE_FAILED, ApprovalOutboxStatus.FAILED)]
    assert dispatch_observations == [(ApprovalInstanceStatus.EXECUTING, ApprovalOutboxStatus.DEFERRED, True)]
    saved_instance, saved_outbox = await _load_bundle(instance.id, outbox.id)
    assert saved_instance.status == ApprovalInstanceStatus.EXECUTING
    assert saved_outbox.status == ApprovalOutboxStatus.DEFERRED
    assert saved_outbox.execution_token == new_token
    assert saved_outbox.payload_snapshot["prepared_token"] == new_token
    async with ApprovalInstanceRepository.decision_session() as session:
        exceptions = list((await session.exec(select(ApprovalException))).all())
    assert [(row.status, row.resolved_action) for row in exceptions] == [("resolved", "resume")]

    assert not await service.complete_deferred_execution(
        tenant_id=42,
        instance_id=instance.id,
        outbox_id=outbox.id,
        execution_token=old_token,
    )


async def test_resume_failure_rolls_back_business_and_approval_and_does_not_dispatch(deferred_db):
    instance, outbox = await _seed_bundle(
        instance_status=ApprovalInstanceStatus.EXECUTE_FAILED,
        outbox_status=ApprovalOutboxStatus.FAILED,
    )
    outbox.execution_token = "generation-1"
    await ApprovalInstanceRepository.update_outbox(outbox)
    dispatch = AsyncMock()

    class Handler:
        async def prepare_resume(self, session, new_token):
            locked_outbox = await session.get(ApprovalOutbox, outbox.id)
            locked_outbox.payload_snapshot = {"prepared_token": new_token}
            session.add(locked_outbox)
            raise RuntimeError("prepare failed")

    service = ApprovalOutboxService(instance_repository=ApprovalInstanceRepository)
    with pytest.raises(RuntimeError, match="prepare failed"):
        await service.resume_deferred_execution(
            tenant_id=42,
            instance_id=instance.id,
            outbox_id=outbox.id,
            handler=Handler(),
            post_commit_dispatch=dispatch,
        )

    dispatch.assert_not_awaited()
    saved_instance, saved_outbox = await _load_bundle(instance.id, outbox.id)
    assert saved_instance.status == ApprovalInstanceStatus.EXECUTE_FAILED
    assert saved_outbox.status == ApprovalOutboxStatus.FAILED
    assert saved_outbox.execution_token == "generation-1"
    assert saved_outbox.payload_snapshot == {"request_id": 88}


async def test_each_failed_resume_uses_a_new_generation_token(deferred_db):
    instance, outbox = await _seed_bundle(
        instance_status=ApprovalInstanceStatus.EXECUTE_FAILED,
        outbox_status=ApprovalOutboxStatus.FAILED,
    )
    outbox.execution_token = "generation-1"
    await ApprovalInstanceRepository.update_outbox(outbox)
    generated: list[str] = []

    class Handler:
        async def prepare_resume(self, _session, new_token):
            generated.append(new_token)
            raise RuntimeError("prepare failed")

    service = ApprovalOutboxService(instance_repository=ApprovalInstanceRepository)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            await service.resume_deferred_execution(
                tenant_id=42,
                instance_id=instance.id,
                outbox_id=outbox.id,
                handler=Handler(),
            )

    assert len(set(generated)) == 2
    assert "generation-1" not in generated
