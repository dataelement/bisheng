from __future__ import annotations

import inspect
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
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
    KnowledgeSpaceFileChangeExecutionCoordinator,
)
from bisheng.knowledge.domain.services.knowledge_space_mutation_executor import (
    DeleteExecutionStepCode,
    MoveExecutionStepCode,
    RenameExecutionStepCode,
    UploadExecutionStepCode,
)
from bisheng.knowledge.domain.services.knowledge_space_mutation_read_projection_service import (
    MUTATION_TRANSITION_ACTIVE_CHECKPOINT_KEY,
    MUTATION_TRANSITION_NEW_VIEW,
    MUTATION_TRANSITION_OLD_VIEW,
    MUTATION_TRANSITION_PHASE_CHECKPOINT_KEY,
)

TENANT_ID = 7
INSTANCE_ID = 812


@pytest_asyncio.fixture
async def saga_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda conn: SQLModel.metadata.create_all(
                conn,
                tables=[
                    KnowledgeSpaceFileChangeRequest.__table__,
                    KnowledgeSpaceFileChangeExecutionStep.__table__,
                ],
            )
        )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
def tenant_context():
    token = set_current_tenant_id(TENANT_ID)
    try:
        yield
    finally:
        current_tenant_id.reset(token)


def _session_factory(engine):
    @asynccontextmanager
    async def factory():
        async with AsyncSession(bind=engine, expire_on_commit=False) as session:
            yield session

    return factory


async def _seed_request(
    engine,
    *,
    state: str,
    token: str | None,
    action: str = KnowledgeSpaceFileChangeAction.RENAME,
    step_states: dict[str, str] | None = None,
    execution_checkpoint: dict | None = None,
) -> int:
    async with AsyncSession(bind=engine, expire_on_commit=False) as session, session.begin():
        request = KnowledgeSpaceFileChangeRequest(
            tenant_id=TENANT_ID,
            space_id=101,
            action=action,
            resource_type=KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE,
            resource_id=501,
            applicant_user_id=9,
            business_key=f"knowledge-space-change:{action}",
            request_fingerprint=f"fingerprint-{action}",
            approval_instance_id=INSTANCE_ID,
            execution_state=state,
            execution_token=token,
            execution_checkpoint=execution_checkpoint or {},
        )
        session.add(request)
        await session.flush()
        for code, step_state in (step_states or {}).items():
            session.add(
                KnowledgeSpaceFileChangeExecutionStep(
                    tenant_id=TENANT_ID,
                    request_id=int(request.id),
                    step_code=code,
                    attempt_token=str(token),
                    idempotency_key=f"f046:{request.id}:{code}",
                    state=step_state,
                )
            )
    return int(request.id)


async def _load(engine, request_id: int):
    async with AsyncSession(bind=engine) as session:
        request = (
            await session.exec(
                select(KnowledgeSpaceFileChangeRequest).where(KnowledgeSpaceFileChangeRequest.id == request_id)
            )
        ).one()
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


def _step(code: str, *, state: str = KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED):
    return KnowledgeSpaceFileChangeExecutionStep(
        tenant_id=TENANT_ID,
        request_id=1,
        step_code=code,
        attempt_token="generation-1",
        idempotency_key=f"f046:1:{code}",
        state=state,
    )


def _request(
    action: str,
    *,
    state: str = KnowledgeSpaceFileChangeExecutionState.APPLIED,
    phase: str | None = None,
):
    checkpoint = {}
    if phase is not None:
        checkpoint = {
            MUTATION_TRANSITION_ACTIVE_CHECKPOINT_KEY: phase == MUTATION_TRANSITION_OLD_VIEW,
            MUTATION_TRANSITION_PHASE_CHECKPOINT_KEY: phase,
        }
    return KnowledgeSpaceFileChangeRequest(
        id=1,
        tenant_id=TENANT_ID,
        space_id=101,
        action=action,
        resource_type=KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE,
        resource_id=501,
        applicant_user_id=9,
        business_key=f"knowledge-space-change:{action}",
        request_fingerprint=f"fingerprint-{action}",
        approval_instance_id=INSTANCE_ID,
        execution_state=state,
        execution_token="generation-1",
        execution_checkpoint=checkpoint,
    )


def test_saga_states_are_knowledge_owned_and_include_retry_and_compensation() -> None:
    assert {
        KnowledgeSpaceFileChangeExecutionState.NOT_STARTED,
        KnowledgeSpaceFileChangeExecutionState.QUEUED,
        KnowledgeSpaceFileChangeExecutionState.APPLYING,
        KnowledgeSpaceFileChangeExecutionState.APPLIED,
        KnowledgeSpaceFileChangeExecutionState.FAILED,
        KnowledgeSpaceFileChangeExecutionState.COMPENSATING,
        KnowledgeSpaceFileChangeExecutionState.CLOSED,
    } == {
        "not_started",
        "queued",
        "applying",
        "applied",
        "failed",
        "compensating",
        "closed",
    }


async def test_queued_claim_failure_and_retry_use_new_knowledge_token_but_same_instance(
    saga_engine,
) -> None:
    request_id = await _seed_request(
        saga_engine,
        state=KnowledgeSpaceFileChangeExecutionState.QUEUED,
        token=None,
        step_states={
            RenameExecutionStepCode.INDEX_SHADOW: KnowledgeSpaceFileChangeExecutionStepState.PENDING,
        },
    )
    tokens = iter(("generation-1", "generation-2"))
    coordinator = KnowledgeSpaceFileChangeExecutionCoordinator(
        session_factory=_session_factory(saga_engine),
        execution_token_factory=lambda: next(tokens),
    )

    first = await coordinator.begin_execution(tenant_id=TENANT_ID, request_id=request_id)
    assert first.execution_token == "generation-1"
    assert (await _load(saga_engine, request_id))[0].execution_state == (
        KnowledgeSpaceFileChangeExecutionState.APPLYING
    )

    assert await coordinator.fail_execution(identity=first, error_summary="OpenFGA timeout")
    failed, _ = await _load(saga_engine, request_id)
    assert failed.execution_state == KnowledgeSpaceFileChangeExecutionState.FAILED
    assert failed.approval_instance_id == INSTANCE_ID

    retry = await coordinator.queue_retry(tenant_id=TENANT_ID, request_id=request_id)
    retried, steps = await _load(saga_engine, request_id)
    assert retry.execution_token == "generation-2"
    assert retried.execution_state == KnowledgeSpaceFileChangeExecutionState.QUEUED
    assert retried.approval_instance_id == INSTANCE_ID
    assert {step.attempt_token for step in steps} == {"generation-2"}
    assert {step.state for step in steps} == {KnowledgeSpaceFileChangeExecutionStepState.PENDING}


@pytest.mark.parametrize(
    ("recovered", "expected"),
    [
        (True, KnowledgeSpaceFileChangeExecutionState.FAILED),
        (False, KnowledgeSpaceFileChangeExecutionState.FAILED),
    ],
)
async def test_compensation_is_a_pure_knowledge_transition(
    saga_engine,
    recovered: bool,
    expected: str,
) -> None:
    request_id = await _seed_request(
        saga_engine,
        state=KnowledgeSpaceFileChangeExecutionState.QUEUED,
        token=None,
    )
    coordinator = KnowledgeSpaceFileChangeExecutionCoordinator(
        session_factory=_session_factory(saga_engine),
        execution_token_factory=lambda: "generation-1",
    )
    identity = await coordinator.begin_execution(tenant_id=TENANT_ID, request_id=request_id)

    assert await coordinator.begin_compensation(identity=identity)
    assert (await _load(saga_engine, request_id))[0].execution_state == (
        KnowledgeSpaceFileChangeExecutionState.COMPENSATING
    )
    assert await coordinator.finish_compensation(identity=identity, recovered=recovered)
    persisted, _ = await _load(saga_engine, request_id)
    assert persisted.execution_state == expected
    assert persisted.approval_instance_id == INSTANCE_ID


async def test_compensation_recovery_requires_action_specific_authority(saga_engine) -> None:
    request_id = await _seed_request(
        saga_engine,
        state=KnowledgeSpaceFileChangeExecutionState.APPLYING,
        token="generation-1",
        action=KnowledgeSpaceFileChangeAction.DELETE,
        step_states=dict.fromkeys(
            DeleteExecutionStepCode.ALL,
            KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED,
        ),
        execution_checkpoint={"delete_phase": "completed", "deletion_cutover_active": False},
    )
    coordinator = KnowledgeSpaceFileChangeExecutionCoordinator(session_factory=_session_factory(saga_engine))
    identity = await coordinator.load_identity_by_request(
        tenant_id=TENANT_ID,
        request_id=request_id,
        execution_token="generation-1",
    )
    assert identity is not None
    assert await coordinator.begin_compensation(identity=identity)
    assert await coordinator.finish_compensation(identity=identity, recovered=True)
    persisted, _ = await _load(saga_engine, request_id)
    assert persisted.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLIED


@pytest.mark.parametrize(
    ("action", "codes"),
    [
        (KnowledgeSpaceFileChangeAction.UPLOAD, UploadExecutionStepCode.BUSINESS_REQUIRED),
        (KnowledgeSpaceFileChangeAction.RENAME, RenameExecutionStepCode.ALL),
        (KnowledgeSpaceFileChangeAction.MOVE, MoveExecutionStepCode.ALL),
        (KnowledgeSpaceFileChangeAction.DELETE, DeleteExecutionStepCode.ALL),
    ],
)
def test_each_action_keeps_its_knowledge_owned_completion_criterion(
    action: str,
    codes: tuple[str, ...],
) -> None:
    request = _request(
        action,
        phase=(
            MUTATION_TRANSITION_NEW_VIEW
            if action in {KnowledgeSpaceFileChangeAction.RENAME, KnowledgeSpaceFileChangeAction.MOVE}
            else None
        ),
    )
    completed = [_step(code) for code in codes]
    incomplete = [
        *completed[:-1],
        _step(codes[-1], state=KnowledgeSpaceFileChangeExecutionStepState.DISPATCHED),
    ]

    if action == KnowledgeSpaceFileChangeAction.DELETE:
        request.execution_checkpoint = {"delete_phase": "completed", "deletion_cutover_active": False}
    assert KnowledgeSpaceFileChangeExecutionCoordinator.is_business_complete(
        request=request,
        steps=completed,
    )
    assert not KnowledgeSpaceFileChangeExecutionCoordinator.is_business_complete(
        request=request,
        steps=incomplete,
    )


@pytest.mark.parametrize(
    "action",
    [KnowledgeSpaceFileChangeAction.RENAME, KnowledgeSpaceFileChangeAction.MOVE],
)
def test_rename_move_old_view_cannot_publish_before_new_view_cutover(action: str) -> None:
    codes = (
        RenameExecutionStepCode.ALL if action == KnowledgeSpaceFileChangeAction.RENAME else MoveExecutionStepCode.ALL
    )
    steps = [_step(code) for code in codes]

    assert not KnowledgeSpaceFileChangeExecutionCoordinator.is_business_complete(
        request=_request(action, phase=MUTATION_TRANSITION_OLD_VIEW),
        steps=steps,
    )
    assert KnowledgeSpaceFileChangeExecutionCoordinator.is_business_complete(
        request=_request(action, phase=MUTATION_TRANSITION_NEW_VIEW),
        steps=steps,
    )


def test_publication_gate_uses_business_state_and_steps_not_approval_status() -> None:
    completed_steps = [_step(code) for code in UploadExecutionStepCode.BUSINESS_REQUIRED]
    applying = _request(
        KnowledgeSpaceFileChangeAction.UPLOAD,
        state=KnowledgeSpaceFileChangeExecutionState.APPLYING,
    )
    applied = _request(
        KnowledgeSpaceFileChangeAction.UPLOAD,
        state=KnowledgeSpaceFileChangeExecutionState.APPLIED,
    )

    assert not KnowledgeSpaceFileChangeExecutionCoordinator.is_publishable(
        request=applying,
        steps=completed_steps,
    )
    assert KnowledgeSpaceFileChangeExecutionCoordinator.is_publishable(
        request=applied,
        steps=completed_steps,
    )


def test_execution_owner_modules_do_not_import_or_write_approval_runtime() -> None:
    from bisheng.knowledge.domain.services import knowledge_space_file_change_execution_coordinator as coordinator
    from bisheng.knowledge.domain.services import knowledge_space_mutation_executor as executor

    source = inspect.getsource(coordinator) + inspect.getsource(executor)
    forbidden = (
        "bisheng.approval",
        "ApprovalInstance",
        "ApprovalOutbox",
        "ApprovalException",
        "Deferred",
        "complete_deferred_execution",
        "fail_deferred_execution",
        "heartbeat_deferred_execution",
    )
    assert not any(token in source for token in forbidden)
