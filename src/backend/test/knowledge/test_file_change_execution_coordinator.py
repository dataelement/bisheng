from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_instance import ApprovalInstanceStatus
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.models.knowledge_space_file_change_execution_step import (
    KnowledgeSpaceFileChangeExecutionStep,
    KnowledgeSpaceFileChangeExecutionStepState,
)
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeAction,
    KnowledgeSpaceFileChangeExecutionState,
    KnowledgeSpaceFileChangeRequest,
    KnowledgeSpaceFileChangeResourceType,
)
from bisheng.knowledge.domain.services.knowledge_space_file_change_execution_coordinator import (
    ExecutionIdentity,
    ExecutionReconcileStatus,
    KnowledgeSpaceFileChangeExecutionCoordinator,
    VerifiedExecutionStepResult,
)
from bisheng.knowledge.domain.services.knowledge_space_mutation_executor import UploadExecutionStepCode


@pytest.fixture
async def coordinator_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(
            SQLModel.metadata.create_all,
            tables=[
                KnowledgeFile.__table__,
                KnowledgeSpaceFileChangeRequest.__table__,
                KnowledgeSpaceFileChangeExecutionStep.__table__,
            ],
        )
    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
def tenant_context():
    token = current_tenant_id.set(42)
    try:
        yield
    finally:
        current_tenant_id.reset(token)


def _session_factory(engine: AsyncEngine):
    @asynccontextmanager
    async def factory():
        async with AsyncSession(bind=engine, expire_on_commit=False) as session:
            yield session

    return factory


async def _seed_upload(
    engine: AsyncEngine,
    *,
    token: str = "generation-1",
    file_status: int = KnowledgeFileStatus.PROCESSING.value,
    step_state: str = KnowledgeSpaceFileChangeExecutionStepState.PENDING,
) -> tuple[int, int]:
    async with AsyncSession(bind=engine, expire_on_commit=False) as session:
        async with session.begin():
            file = KnowledgeFile(
                tenant_id=42,
                knowledge_id=8,
                user_id=7,
                file_name="report.pdf",
                status=file_status,
            )
            session.add(file)
            await session.flush()
            request = KnowledgeSpaceFileChangeRequest(
                tenant_id=42,
                space_id=8,
                action=KnowledgeSpaceFileChangeAction.UPLOAD,
                resource_type=KnowledgeSpaceFileChangeResourceType.STAGED_UPLOAD,
                applicant_user_id=7,
                approval_instance_id=101,
                executed_resource_id=int(file.id),
                execution_state=KnowledgeSpaceFileChangeExecutionState.APPLYING,
                execution_token=token,
                execution_checkpoint={"deadline": "2026-08-12T00:00:00+00:00"},
            )
            session.add(request)
            await session.flush()
            for code in UploadExecutionStepCode.ALL:
                session.add(
                    KnowledgeSpaceFileChangeExecutionStep(
                        tenant_id=42,
                        request_id=int(request.id),
                        step_code=code,
                        attempt_token=token,
                        idempotency_key=f"f046:{request.id}:{code}",
                        state=step_state,
                    )
                )
    return int(request.id), int(file.id)


async def _seed_rename(engine: AsyncEngine, *, token: str = "generation-1") -> int:
    async with AsyncSession(bind=engine, expire_on_commit=False) as session:
        async with session.begin():
            request = KnowledgeSpaceFileChangeRequest(
                tenant_id=42,
                space_id=8,
                action=KnowledgeSpaceFileChangeAction.RENAME,
                resource_type=KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE,
                resource_id=90,
                applicant_user_id=7,
                approval_instance_id=101,
                execution_state=KnowledgeSpaceFileChangeExecutionState.APPLYING,
                execution_token=token,
                execution_checkpoint={"mutation_manifest": {"root": {"id": 90}}},
            )
            session.add(request)
            await session.flush()
            for code in ("rename.index_shadow", "rename.verify", "rename.db_cutover"):
                session.add(
                    KnowledgeSpaceFileChangeExecutionStep(
                        tenant_id=42,
                        request_id=int(request.id),
                        step_code=code,
                        attempt_token=token,
                        idempotency_key=f"f046:{request.id}:{code}",
                    )
                )
    return int(request.id)


async def _seed_delete(engine: AsyncEngine, *, token: str = "generation-1") -> int:
    async with AsyncSession(bind=engine, expire_on_commit=False) as session:
        async with session.begin():
            request = KnowledgeSpaceFileChangeRequest(
                tenant_id=42,
                space_id=8,
                action=KnowledgeSpaceFileChangeAction.DELETE,
                resource_type=KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE,
                resource_id=90,
                applicant_user_id=7,
                approval_instance_id=101,
                execution_state=KnowledgeSpaceFileChangeExecutionState.APPLYING,
                execution_token=token,
                execution_checkpoint={"delete_manifest": {"root": {"id": 90}}},
            )
            session.add(request)
            await session.flush()
            for code, state in (
                ("delete.prepare", KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED),
                ("delete.db_cutover", KnowledgeSpaceFileChangeExecutionStepState.PENDING),
                ("delete.fga_purge", KnowledgeSpaceFileChangeExecutionStepState.PENDING),
                ("delete.minio_purge", KnowledgeSpaceFileChangeExecutionStepState.PENDING),
                ("delete.es_purge", KnowledgeSpaceFileChangeExecutionStepState.PENDING),
                ("delete.milvus_purge", KnowledgeSpaceFileChangeExecutionStepState.PENDING),
            ):
                session.add(
                    KnowledgeSpaceFileChangeExecutionStep(
                        tenant_id=42,
                        request_id=int(request.id),
                        step_code=code,
                        attempt_token=token,
                        idempotency_key=f"f046:{request.id}:{code}",
                        state=state,
                    )
                )
    return int(request.id)


def _identity(request_id: int, *, token: str = "generation-1") -> ExecutionIdentity:
    return ExecutionIdentity(
        tenant_id=42,
        request_id=request_id,
        instance_id=101,
        outbox_id=201,
        execution_token=token,
    )


def _coordinator(engine: AsyncEngine, outbox_service=None, mutation_cutover=None, delete_purge=None):
    outbox = outbox_service or SimpleNamespace(
        heartbeat_deferred_execution=AsyncMock(return_value=True),
        complete_deferred_execution=AsyncMock(return_value=True),
        fail_deferred_execution=AsyncMock(return_value=True),
    )
    return (
        KnowledgeSpaceFileChangeExecutionCoordinator(
            session_factory=_session_factory(engine),
            approval_outbox_service=outbox,
            mutation_cutover=mutation_cutover,
            delete_purge=delete_purge,
        ),
        outbox,
    )


async def _steps(engine: AsyncEngine, request_id: int):
    async with AsyncSession(bind=engine, expire_on_commit=False) as session:
        return list(
            (
                await session.exec(
                    select(KnowledgeSpaceFileChangeExecutionStep)
                    .where(KnowledgeSpaceFileChangeExecutionStep.request_id == request_id)
                    .order_by(KnowledgeSpaceFileChangeExecutionStep.id)
                )
            ).all()
        )


async def _request(engine: AsyncEngine, request_id: int):
    async with AsyncSession(bind=engine, expire_on_commit=False) as session:
        return await session.get(KnowledgeSpaceFileChangeRequest, request_id)


async def test_same_generation_redispatch_reuses_stable_idempotency_key(coordinator_engine):
    set_current_tenant_id(42)
    request_id, _ = await _seed_upload(coordinator_engine)
    coordinator, _ = _coordinator(coordinator_engine)
    dispatched: list[tuple[str, str, str]] = []

    async def dispatch(context):
        dispatched.append((context.step_code, context.idempotency_key, context.execution_token))
        return f"task-{len(dispatched)}"

    first = await coordinator.dispatch_ready_steps(identity=_identity(request_id), dispatcher=dispatch)
    second = await coordinator.dispatch_ready_steps(identity=_identity(request_id), dispatcher=dispatch)

    assert first == second == [UploadExecutionStepCode.FGA]
    assert dispatched == [
        (UploadExecutionStepCode.FGA, f"f046:{request_id}:upload.fga", "generation-1"),
        (UploadExecutionStepCode.FGA, f"f046:{request_id}:upload.fga", "generation-1"),
    ]


async def test_worker_entry_resolves_current_deferred_identity_without_approval_orm(coordinator_engine):
    set_current_tenant_id(42)
    request_id, _ = await _seed_upload(coordinator_engine)
    outbox = SimpleNamespace(
        id=201,
        tenant_id=42,
        instance_id=101,
        status="deferred",
        execution_token="generation-1",
    )
    loader = AsyncMock(return_value=outbox)
    coordinator, _ = _coordinator(coordinator_engine)
    coordinator.outbox_loader = loader
    coordinator.instance_outboxes_loader = AsyncMock(return_value=[outbox])

    identity = await coordinator.load_identity(
        tenant_id=42,
        outbox_id=201,
        execution_token="generation-1",
    )
    stale = await coordinator.load_identity(
        tenant_id=42,
        outbox_id=201,
        execution_token="old-generation",
    )

    assert identity == _identity(request_id)
    assert stale is None
    loader.assert_awaited()
    assert await coordinator.load_identity_by_request(
        tenant_id=42,
        request_id=request_id,
        execution_token="generation-1",
    ) == _identity(request_id)
    assert (
        await coordinator.load_identity_by_request(
            tenant_id=42,
            request_id=request_id,
            execution_token="old-generation",
        )
        is None
    )


async def test_legacy_upload_terminal_ack_completes_parser_handoff_only(coordinator_engine):
    set_current_tenant_id(42)
    request_id, file_id = await _seed_upload(
        coordinator_engine,
        file_status=KnowledgeFileStatus.SUCCESS.value,
    )
    async with AsyncSession(bind=coordinator_engine, expire_on_commit=False) as session:
        async with session.begin():
            rows = list(
                (
                    await session.exec(
                        select(KnowledgeSpaceFileChangeExecutionStep).where(
                            KnowledgeSpaceFileChangeExecutionStep.request_id == request_id
                        )
                    )
                ).all()
            )
            fga = next(row for row in rows if row.step_code == UploadExecutionStepCode.FGA)
            fga.state = KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED
            session.add(fga)
    outbox_row = SimpleNamespace(
        id=201,
        tenant_id=42,
        instance_id=101,
        status="deferred",
        execution_token="generation-1",
    )
    coordinator, outbox = _coordinator(coordinator_engine)
    coordinator.instance_outboxes_loader = AsyncMock(return_value=[outbox_row])

    status = await coordinator.acknowledge_upload_terminal(
        tenant_id=42,
        request_id=request_id,
        execution_token="generation-1",
        file_id=file_id,
    )

    assert status == ExecutionReconcileStatus.COMPLETED
    by_code = {row.step_code: row for row in await _steps(coordinator_engine, request_id)}
    assert by_code[UploadExecutionStepCode.PARSE].state == KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED
    assert by_code[UploadExecutionStepCode.PARSE].result_digest == f"legacy-parser-handoff:file:{file_id}"
    for code in (UploadExecutionStepCode.INDEX, UploadExecutionStepCode.VECTOR):
        assert by_code[code].state == KnowledgeSpaceFileChangeExecutionStepState.PENDING
    outbox.complete_deferred_execution.assert_awaited_once()


async def test_upload_terminal_failure_does_not_regress_completed_business_handoff(coordinator_engine):
    set_current_tenant_id(42)
    request_id, file_id = await _seed_upload(
        coordinator_engine,
        file_status=KnowledgeFileStatus.FAILED.value,
        step_state=KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED,
    )
    outbox_row = SimpleNamespace(
        id=201,
        tenant_id=42,
        instance_id=101,
        status="deferred",
        execution_token="generation-1",
    )
    coordinator, outbox = _coordinator(coordinator_engine)
    coordinator.instance_outboxes_loader = AsyncMock(return_value=[outbox_row])

    status = await coordinator.acknowledge_upload_terminal(
        tenant_id=42,
        request_id=request_id,
        execution_token="generation-1",
        file_id=file_id,
    )

    assert status == ExecutionReconcileStatus.COMPLETED
    outbox.complete_deferred_execution.assert_awaited_once()
    outbox.fail_deferred_execution.assert_not_awaited()
    assert (await _request(coordinator_engine, request_id)).execution_state == (
        KnowledgeSpaceFileChangeExecutionState.APPLIED
    )


async def test_upload_dispatch_follows_real_parser_chain_and_never_fabricates_index_tasks(coordinator_engine):
    set_current_tenant_id(42)
    request_id, _ = await _seed_upload(coordinator_engine)
    coordinator, _ = _coordinator(coordinator_engine)
    dispatched: list[str] = []

    async def dispatch(context):
        dispatched.append(context.step_code)
        return f"task:{context.step_code}"

    await coordinator.acknowledge_step(
        identity=_identity(request_id),
        step_code=UploadExecutionStepCode.FGA,
        verifier=AsyncMock(return_value=VerifiedExecutionStepResult("fga:verified")),
    )
    assert await coordinator.dispatch_ready_steps(identity=_identity(request_id), dispatcher=dispatch) == [
        UploadExecutionStepCode.PARSE
    ]
    await coordinator.acknowledge_step(
        identity=_identity(request_id),
        step_code=UploadExecutionStepCode.PARSE,
        verifier=AsyncMock(return_value=VerifiedExecutionStepResult("parse:verified")),
    )

    assert await coordinator.dispatch_ready_steps(identity=_identity(request_id), dispatcher=dispatch) == []
    assert dispatched == [UploadExecutionStepCode.PARSE]


async def test_rename_dependencies_unlock_in_order_and_internal_cutover_never_hits_broker(coordinator_engine):
    set_current_tenant_id(42)
    request_id = await _seed_rename(coordinator_engine)
    dispatched: list[str] = []

    async def dispatch(context):
        dispatched.append(context.step_code)
        return f"task:{context.step_code}"

    async def cutover(identity):
        async with AsyncSession(bind=coordinator_engine, expire_on_commit=False) as session:
            async with session.begin():
                request = await session.get(KnowledgeSpaceFileChangeRequest, identity.request_id)
                request.execution_state = KnowledgeSpaceFileChangeExecutionState.APPLIED
                session.add(request)
                rows = list(
                    (
                        await session.exec(
                            select(KnowledgeSpaceFileChangeExecutionStep).where(
                                KnowledgeSpaceFileChangeExecutionStep.request_id == identity.request_id
                            )
                        )
                    ).all()
                )
                cutover_step = next(row for row in rows if row.step_code == "rename.db_cutover")
                cutover_step.state = KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED
                cutover_step.result_digest = "db:verified"
                session.add(cutover_step)
        return True

    coordinator, outbox = _coordinator(coordinator_engine, mutation_cutover=cutover)
    identity = _identity(request_id)

    assert await coordinator.dispatch_ready_steps(identity=identity, dispatcher=dispatch) == ["rename.index_shadow"]
    await coordinator.acknowledge_step(
        identity=identity,
        step_code="rename.index_shadow",
        verifier=AsyncMock(return_value=VerifiedExecutionStepResult("shadow:verified")),
    )
    assert await coordinator.dispatch_ready_steps(identity=identity, dispatcher=dispatch) == ["rename.verify"]
    status = await coordinator.acknowledge_step(
        identity=identity,
        step_code="rename.verify",
        verifier=AsyncMock(return_value=VerifiedExecutionStepResult("verify:verified")),
    )

    assert status == ExecutionReconcileStatus.COMPLETED
    assert dispatched == ["rename.index_shadow", "rename.verify"]
    assert "rename.db_cutover" not in dispatched
    # Rename/move owner cutover completes DB visibility + F025 terminal in the
    # same caller-owned UoW; the coordinator must not issue a second commit.
    outbox.complete_deferred_execution.assert_not_awaited()


async def test_delete_calls_owner_cutover_then_purge_without_generic_complete(coordinator_engine):
    set_current_tenant_id(42)
    request_id = await _seed_delete(coordinator_engine)

    async def cutover(identity):
        async with AsyncSession(bind=coordinator_engine, expire_on_commit=False) as session:
            async with session.begin():
                request = await session.get(KnowledgeSpaceFileChangeRequest, identity.request_id)
                request.execution_state = KnowledgeSpaceFileChangeExecutionState.APPLYING
                request.execution_checkpoint = {
                    **(request.execution_checkpoint or {}),
                    "delete_phase": "purging",
                    "deletion_cutover_active": True,
                }
                session.add(request)
                rows = list(
                    (
                        await session.exec(
                            select(KnowledgeSpaceFileChangeExecutionStep).where(
                                KnowledgeSpaceFileChangeExecutionStep.request_id == identity.request_id
                            )
                        )
                    ).all()
                )
                step = next(row for row in rows if row.step_code == "delete.db_cutover")
                step.state = KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED
                session.add(step)
        return True

    async def purge(identity):
        async with AsyncSession(bind=coordinator_engine, expire_on_commit=False) as session:
            async with session.begin():
                request = await session.get(KnowledgeSpaceFileChangeRequest, identity.request_id)
                request.execution_state = KnowledgeSpaceFileChangeExecutionState.APPLIED
                request.execution_checkpoint = {
                    **(request.execution_checkpoint or {}),
                    "delete_phase": "completed",
                    "deletion_cutover_active": False,
                }
                rows = list(
                    (
                        await session.exec(
                            select(KnowledgeSpaceFileChangeExecutionStep).where(
                                KnowledgeSpaceFileChangeExecutionStep.request_id == identity.request_id
                            )
                        )
                    ).all()
                )
                for row in rows:
                    row.state = KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED
                    session.add(row)
                session.add(request)
        return True

    purge = AsyncMock(side_effect=purge)
    coordinator, outbox = _coordinator(
        coordinator_engine,
        mutation_cutover=cutover,
        delete_purge=purge,
    )
    dispatcher = AsyncMock()

    assert (
        await coordinator.dispatch_ready_steps(
            identity=_identity(request_id),
            dispatcher=dispatcher,
        )
        == []
    )
    status = await coordinator.reconcile(identity=_identity(request_id))

    assert status == ExecutionReconcileStatus.COMPLETED
    dispatcher.assert_not_awaited()
    outbox.complete_deferred_execution.assert_not_awaited()
    purge.assert_awaited_once_with(_identity(request_id))


async def test_old_generation_ack_is_ignored_without_running_authoritative_verifier(coordinator_engine):
    set_current_tenant_id(42)
    request_id, _ = await _seed_upload(coordinator_engine)
    coordinator, outbox = _coordinator(coordinator_engine)
    verifier = AsyncMock(return_value=VerifiedExecutionStepResult("digest"))

    status = await coordinator.acknowledge_step(
        identity=_identity(request_id, token="old-generation"),
        step_code=UploadExecutionStepCode.PARSE,
        verifier=verifier,
    )

    assert status == ExecutionReconcileStatus.IGNORED
    verifier.assert_not_awaited()
    outbox.complete_deferred_execution.assert_not_awaited()
    parse = next(step for step in await _steps(coordinator_engine, request_id) if step.step_code == "upload.parse")
    assert parse.state == KnowledgeSpaceFileChangeExecutionStepState.PENDING


async def test_failed_generation_cannot_dispatch_or_ack_until_new_token_resume(coordinator_engine):
    set_current_tenant_id(42)
    request_id, _ = await _seed_upload(coordinator_engine)
    async with AsyncSession(bind=coordinator_engine, expire_on_commit=False) as session:
        async with session.begin():
            request = await session.get(KnowledgeSpaceFileChangeRequest, request_id)
            request.execution_state = KnowledgeSpaceFileChangeExecutionState.FAILED
            session.add(request)
    coordinator, _ = _coordinator(coordinator_engine)
    dispatcher = AsyncMock(return_value="task-id")
    verifier = AsyncMock(return_value=VerifiedExecutionStepResult("verified"))

    assert (
        await coordinator.dispatch_ready_steps(
            identity=_identity(request_id),
            dispatcher=dispatcher,
        )
        == []
    )
    assert (
        await coordinator.acknowledge_step(
            identity=_identity(request_id),
            step_code=UploadExecutionStepCode.FGA,
            verifier=verifier,
        )
        == ExecutionReconcileStatus.IGNORED
    )
    dispatcher.assert_not_awaited()
    verifier.assert_not_awaited()

    async with AsyncSession(bind=coordinator_engine, expire_on_commit=False) as session:
        async with session.begin():
            await coordinator.prepare_resume_in_uow(
                session=session,
                request_id=request_id,
                new_token="generation-2",
            )
    assert await coordinator.dispatch_ready_steps(
        identity=_identity(request_id, token="generation-2"),
        dispatcher=dispatcher,
    ) == [UploadExecutionStepCode.FGA]


async def test_failed_step_is_not_same_generation_dispatchable_before_request_failure_reconcile(coordinator_engine):
    set_current_tenant_id(42)
    request_id, _ = await _seed_upload(coordinator_engine)
    async with AsyncSession(bind=coordinator_engine, expire_on_commit=False) as session:
        async with session.begin():
            steps = list(
                (
                    await session.exec(
                        select(KnowledgeSpaceFileChangeExecutionStep).where(
                            KnowledgeSpaceFileChangeExecutionStep.request_id == request_id
                        )
                    )
                ).all()
            )
            fga = next(step for step in steps if step.step_code == UploadExecutionStepCode.FGA)
            fga.state = KnowledgeSpaceFileChangeExecutionStepState.FAILED
            session.add(fga)
    coordinator, _ = _coordinator(coordinator_engine)
    dispatcher = AsyncMock(return_value="task-id")
    verifier = AsyncMock(return_value=VerifiedExecutionStepResult("late"))

    assert (
        await coordinator.dispatch_ready_steps(
            identity=_identity(request_id),
            dispatcher=dispatcher,
        )
        == []
    )
    assert (
        await coordinator.acknowledge_step(
            identity=_identity(request_id),
            step_code=UploadExecutionStepCode.FGA,
            verifier=verifier,
        )
        == ExecutionReconcileStatus.IGNORED
    )
    dispatcher.assert_not_awaited()
    verifier.assert_not_awaited()


async def test_raw_task_receipt_cannot_ack_a_step_as_succeeded(coordinator_engine):
    set_current_tenant_id(42)
    request_id, _ = await _seed_upload(coordinator_engine)
    coordinator, _ = _coordinator(coordinator_engine)

    with pytest.raises(TypeError, match="authoritative"):
        await coordinator.acknowledge_step(
            identity=_identity(request_id),
            step_code=UploadExecutionStepCode.PARSE,
            verifier=AsyncMock(return_value="celery-task-id"),
        )

    parse = next(step for step in await _steps(coordinator_engine, request_id) if step.step_code == "upload.parse")
    assert parse.state != KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED


async def test_duplicate_verified_ack_is_idempotent(coordinator_engine):
    set_current_tenant_id(42)
    request_id, _ = await _seed_upload(coordinator_engine)
    coordinator, _ = _coordinator(coordinator_engine)
    verifier = AsyncMock(return_value=VerifiedExecutionStepResult("parse:v1"))

    first = await coordinator.acknowledge_step(
        identity=_identity(request_id),
        step_code=UploadExecutionStepCode.PARSE,
        verifier=verifier,
    )
    second = await coordinator.acknowledge_step(
        identity=_identity(request_id),
        step_code=UploadExecutionStepCode.PARSE,
        verifier=verifier,
    )

    assert first == second == ExecutionReconcileStatus.RUNNING
    parse = next(step for step in await _steps(coordinator_engine, request_id) if step.step_code == "upload.parse")
    assert parse.state == KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED
    assert parse.result_digest == "parse:v1"


async def test_upload_completes_after_permission_and_parser_handoff_are_authoritative(coordinator_engine):
    set_current_tenant_id(42)
    request_id, file_id = await _seed_upload(
        coordinator_engine,
        file_status=KnowledgeFileStatus.SUCCESS.value,
        step_state=KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED,
    )
    coordinator, outbox = _coordinator(coordinator_engine)

    status = await coordinator.reconcile(identity=_identity(request_id))

    assert status == ExecutionReconcileStatus.COMPLETED
    assert (await _request(coordinator_engine, request_id)).execution_state == (
        KnowledgeSpaceFileChangeExecutionState.APPLIED
    )
    outbox.complete_deferred_execution.assert_awaited_once_with(
        tenant_id=42,
        instance_id=101,
        outbox_id=201,
        execution_token="generation-1",
    )
    assert file_id > 0


async def test_processing_upload_completes_approval_after_business_handoff(coordinator_engine):
    set_current_tenant_id(42)
    request_id, _ = await _seed_upload(
        coordinator_engine,
        file_status=KnowledgeFileStatus.PROCESSING.value,
        step_state=KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED,
    )
    coordinator, outbox = _coordinator(coordinator_engine)

    status = await coordinator.reconcile(identity=_identity(request_id))

    assert status == ExecutionReconcileStatus.COMPLETED
    outbox.heartbeat_deferred_execution.assert_not_awaited()
    outbox.complete_deferred_execution.assert_awaited_once()
    assert (await _request(coordinator_engine, request_id)).execution_state == (
        KnowledgeSpaceFileChangeExecutionState.APPLIED
    )


async def test_parse_failure_does_not_fail_approval_after_business_handoff(coordinator_engine):
    set_current_tenant_id(42)
    request_id, _ = await _seed_upload(
        coordinator_engine,
        file_status=KnowledgeFileStatus.FAILED.value,
        step_state=KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED,
    )
    coordinator, outbox = _coordinator(coordinator_engine)

    status = await coordinator.reconcile(identity=_identity(request_id))

    assert status == ExecutionReconcileStatus.COMPLETED
    request = await _request(coordinator_engine, request_id)
    assert request.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLIED
    assert "failure_reason" not in request.execution_checkpoint
    outbox.complete_deferred_execution.assert_awaited_once()
    outbox.fail_deferred_execution.assert_not_awaited()


async def test_projection_uses_business_execution_status_without_parser_states(coordinator_engine):
    set_current_tenant_id(42)
    request_id, _ = await _seed_upload(
        coordinator_engine,
        file_status=KnowledgeFileStatus.PROCESSING.value,
    )
    coordinator, _ = _coordinator(coordinator_engine)
    request = await _request(coordinator_engine, request_id)
    running_instance = SimpleNamespace(
        tenant_id=42,
        id=101,
        status=ApprovalInstanceStatus.EXECUTING,
        payload_snapshot={"change_request_id": request_id},
        business_resource_id=str(request_id),
    )
    executed_instance = SimpleNamespace(**{**running_instance.__dict__, "status": ApprovalInstanceStatus.EXECUTED})

    running = await coordinator.get_business_status_projection(instance=running_instance, request=request)
    inconsistent = await coordinator.get_business_status_projection(instance=executed_instance, request=request)

    assert running["status"] == "executing"
    assert inconsistent["status"] == "execute_failed"
    assert inconsistent["failure_reason"] == "business execution is incomplete"


async def test_prepare_resume_resets_only_incomplete_steps_to_new_token(coordinator_engine):
    set_current_tenant_id(42)
    request_id, _ = await _seed_upload(coordinator_engine)
    async with AsyncSession(bind=coordinator_engine, expire_on_commit=False) as session:
        async with session.begin():
            request = await session.get(KnowledgeSpaceFileChangeRequest, request_id)
            request.execution_state = KnowledgeSpaceFileChangeExecutionState.FAILED
            session.add(request)
            steps = list(
                (
                    await session.exec(
                        select(KnowledgeSpaceFileChangeExecutionStep).where(
                            KnowledgeSpaceFileChangeExecutionStep.request_id == request_id
                        )
                    )
                ).all()
            )
            steps[0].state = KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED
            steps[1].state = KnowledgeSpaceFileChangeExecutionStepState.FAILED
            session.add_all(steps)

    deadline = datetime.now(UTC) + timedelta(hours=2)
    coordinator = KnowledgeSpaceFileChangeExecutionCoordinator(
        session_factory=_session_factory(coordinator_engine),
        deadline_factory=lambda: deadline,
    )
    async with AsyncSession(bind=coordinator_engine, expire_on_commit=False) as session:
        async with session.begin():
            result = await coordinator.prepare_resume_in_uow(
                session=session,
                request_id=request_id,
                new_token="generation-2",
            )

    assert result.execution_token == "generation-2"
    assert result.deadline == deadline
    request = await _request(coordinator_engine, request_id)
    assert request.execution_token == "generation-2"
    assert request.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLYING
    by_code = {step.step_code: step for step in await _steps(coordinator_engine, request_id)}
    assert by_code[UploadExecutionStepCode.FGA].attempt_token == "generation-1"
    assert by_code[UploadExecutionStepCode.FGA].state == KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED
    assert by_code[UploadExecutionStepCode.PARSE].attempt_token == "generation-2"
    assert by_code[UploadExecutionStepCode.PARSE].state == KnowledgeSpaceFileChangeExecutionStepState.PENDING
