from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
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
from bisheng.knowledge.domain.services.knowledge_space_mutation_executor import (
    RenameExecutionStepCode,
    UploadExecutionStepCode,
)

TENANT_ID = 42


@pytest.fixture
async def coordinator_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(
            SQLModel.metadata.create_all,
            tables=[
                KnowledgeSpaceFileChangeRequest.__table__,
                KnowledgeSpaceFileChangeExecutionStep.__table__,
            ],
        )
    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
def tenant_context():
    token = set_current_tenant_id(TENANT_ID)
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


async def _seed(
    engine: AsyncEngine,
    *,
    action: str = KnowledgeSpaceFileChangeAction.UPLOAD,
    state: str = KnowledgeSpaceFileChangeExecutionState.APPLYING,
    token: str | None = "generation-1",
) -> int:
    codes = (
        UploadExecutionStepCode.BUSINESS_REQUIRED
        if action == KnowledgeSpaceFileChangeAction.UPLOAD
        else RenameExecutionStepCode.ALL
    )
    async with AsyncSession(bind=engine, expire_on_commit=False) as session, session.begin():
        request = KnowledgeSpaceFileChangeRequest(
            tenant_id=TENANT_ID,
            space_id=8,
            action=action,
            resource_type=KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE,
            resource_id=90,
            applicant_user_id=7,
            business_key=f"knowledge-space-change:coordinator:{action}",
            request_fingerprint=f"coordinator-{action}-fingerprint",
            approval_instance_id=101,
            execution_state=state,
            execution_token=token,
        )
        session.add(request)
        await session.flush()
        for code in codes:
            session.add(
                KnowledgeSpaceFileChangeExecutionStep(
                    tenant_id=TENANT_ID,
                    request_id=int(request.id),
                    step_code=code,
                    attempt_token=str(token),
                    idempotency_key=f"f046:{request.id}:{code}",
                )
            )
    return int(request.id)


def _coordinator(engine: AsyncEngine, **kwargs):
    return KnowledgeSpaceFileChangeExecutionCoordinator(
        session_factory=_session_factory(engine),
        **kwargs,
    )


def _identity(request_id: int, token: str = "generation-1") -> ExecutionIdentity:
    return ExecutionIdentity(
        tenant_id=TENANT_ID,
        request_id=request_id,
        execution_token=token,
    )


async def _rows(engine: AsyncEngine, request_id: int):
    async with AsyncSession(bind=engine) as session:
        request = await session.get(KnowledgeSpaceFileChangeRequest, request_id)
        steps = list(
            (
                await session.exec(
                    select(KnowledgeSpaceFileChangeExecutionStep).where(
                        KnowledgeSpaceFileChangeExecutionStep.request_id == request_id
                    )
                )
            ).all()
        )
    return request, steps


async def test_same_generation_redispatch_reuses_stable_idempotency_key(coordinator_engine) -> None:
    request_id = await _seed(coordinator_engine)
    coordinator = _coordinator(coordinator_engine)
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


async def test_old_generation_ack_is_ignored_before_verifier(coordinator_engine) -> None:
    request_id = await _seed(coordinator_engine)
    verifier = AsyncMock(return_value=VerifiedExecutionStepResult("verified"))

    status = await _coordinator(coordinator_engine).acknowledge_step(
        identity=_identity(request_id, "old-generation"),
        step_code=UploadExecutionStepCode.FGA,
        verifier=verifier,
    )

    assert status == ExecutionReconcileStatus.IGNORED
    verifier.assert_not_awaited()


async def test_raw_broker_receipt_is_not_authoritative_acknowledgement(coordinator_engine) -> None:
    request_id = await _seed(coordinator_engine)
    with pytest.raises(TypeError, match="authoritative"):
        await _coordinator(coordinator_engine).acknowledge_step(
            identity=_identity(request_id),
            step_code=UploadExecutionStepCode.FGA,
            verifier=AsyncMock(return_value="celery-task-id"),
        )


async def test_duplicate_verified_ack_is_idempotent(coordinator_engine) -> None:
    request_id = await _seed(coordinator_engine)
    coordinator = _coordinator(coordinator_engine)
    verifier = AsyncMock(return_value=VerifiedExecutionStepResult("fga:v1"))

    first = await coordinator.acknowledge_step(
        identity=_identity(request_id),
        step_code=UploadExecutionStepCode.FGA,
        verifier=verifier,
    )
    second = await coordinator.acknowledge_step(
        identity=_identity(request_id),
        step_code=UploadExecutionStepCode.FGA,
        verifier=verifier,
    )

    assert first == second == ExecutionReconcileStatus.RUNNING
    _, steps = await _rows(coordinator_engine, request_id)
    row = next(step for step in steps if step.step_code == UploadExecutionStepCode.FGA)
    assert row.state == KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED
    assert row.result_digest == "fga:v1"


async def test_rename_external_steps_unlock_in_order_and_cutover_stays_internal(coordinator_engine) -> None:
    request_id = await _seed(coordinator_engine, action=KnowledgeSpaceFileChangeAction.RENAME)
    cutover = AsyncMock(return_value=True)
    coordinator = _coordinator(coordinator_engine, mutation_cutover=cutover)
    dispatched: list[str] = []

    async def dispatch(context):
        dispatched.append(context.step_code)
        return context.step_code

    assert await coordinator.dispatch_ready_steps(identity=_identity(request_id), dispatcher=dispatch) == [
        RenameExecutionStepCode.INDEX_SHADOW
    ]
    await coordinator.acknowledge_step(
        identity=_identity(request_id),
        step_code=RenameExecutionStepCode.INDEX_SHADOW,
        verifier=AsyncMock(return_value=VerifiedExecutionStepResult("shadow:v1")),
    )
    assert await coordinator.dispatch_ready_steps(identity=_identity(request_id), dispatcher=dispatch) == [
        RenameExecutionStepCode.VERIFY
    ]
    status = await coordinator.acknowledge_step(
        identity=_identity(request_id),
        step_code=RenameExecutionStepCode.VERIFY,
        verifier=AsyncMock(return_value=VerifiedExecutionStepResult("verify:v1")),
    )

    assert status == ExecutionReconcileStatus.COMPLETED
    assert dispatched == [RenameExecutionStepCode.INDEX_SHADOW, RenameExecutionStepCode.VERIFY]
    assert RenameExecutionStepCode.DB_CUTOVER not in dispatched
    cutover.assert_awaited_once_with(_identity(request_id))


async def test_failed_step_marks_only_knowledge_request_failed(coordinator_engine) -> None:
    request_id = await _seed(coordinator_engine)
    async with AsyncSession(bind=coordinator_engine, expire_on_commit=False) as session, session.begin():
        steps = list(
            (
                await session.exec(
                    select(KnowledgeSpaceFileChangeExecutionStep).where(
                        KnowledgeSpaceFileChangeExecutionStep.request_id == request_id
                    )
                )
            ).all()
        )
        steps[0].state = KnowledgeSpaceFileChangeExecutionStepState.FAILED
        session.add(steps[0])

    status = await _coordinator(coordinator_engine).reconcile(identity=_identity(request_id))
    request, _ = await _rows(coordinator_engine, request_id)
    assert status == ExecutionReconcileStatus.FAILED
    assert request.execution_state == KnowledgeSpaceFileChangeExecutionState.FAILED
    assert request.approval_instance_id == 101


async def test_failed_request_retry_preserves_succeeded_steps_and_resets_incomplete(coordinator_engine) -> None:
    request_id = await _seed(coordinator_engine, state=KnowledgeSpaceFileChangeExecutionState.FAILED)
    async with AsyncSession(bind=coordinator_engine, expire_on_commit=False) as session, session.begin():
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
    coordinator = _coordinator(coordinator_engine, execution_token_factory=lambda: "generation-2")

    identity = await coordinator.queue_retry(tenant_id=TENANT_ID, request_id=request_id)
    request, steps = await _rows(coordinator_engine, request_id)
    by_code = {step.step_code: step for step in steps}

    assert identity.execution_token == "generation-2"
    assert request.execution_state == KnowledgeSpaceFileChangeExecutionState.QUEUED
    assert by_code[UploadExecutionStepCode.FGA].state == KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED
    assert by_code[UploadExecutionStepCode.FGA].attempt_token == "generation-1"
    assert by_code[UploadExecutionStepCode.PARSE].state == KnowledgeSpaceFileChangeExecutionStepState.PENDING
    assert by_code[UploadExecutionStepCode.PARSE].attempt_token == "generation-2"


async def test_execution_rejects_mismatched_tenant_context(coordinator_engine) -> None:
    request_id = await _seed(
        coordinator_engine,
        state=KnowledgeSpaceFileChangeExecutionState.QUEUED,
        token=None,
    )
    token = set_current_tenant_id(41)
    try:
        with pytest.raises(RuntimeError, match="tenant"):
            await _coordinator(coordinator_engine).begin_execution(
                tenant_id=TENANT_ID,
                request_id=request_id,
            )
    finally:
        current_tenant_id.reset(token)
