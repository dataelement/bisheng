"""Two ways an F046 request could never reach a terminal state.

Both were found on a live tenant, where a knowledge-space file sat at "waiting
to execute" for six hours and could not be deleted:

1. A step whose `upload.fga` work could never succeed was re-dispatched 989
   times.  Celery's per-attempt retries are capped, but the watchdog and the
   step recovery kept handing the work back, and every dispatch refreshed the
   request heartbeat -- which is the very signal the watchdog uses to decide a
   request is dead.  The retry fed the watchdog that was supposed to stop it.

2. A second request had its approval decision delivered, committed `queued`,
   and then lost the business dispatch that should have followed.  It owned no
   execution token and no steps, and nothing scans `queued`: the delivery layer
   considers a delivered decision finished, while the watchdog and the step
   recovery both require `applying` or `compensating`.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

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
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_compensation_repository import (
    KnowledgeSpaceFileChangeCompensationRepository,
)
from bisheng.knowledge.domain.services.knowledge_space_file_change_execution_coordinator import (
    MAX_STEP_DISPATCH_ATTEMPTS,
    ExecutionIdentity,
    ExecutionReconcileStatus,
    KnowledgeSpaceFileChangeExecutionCoordinator,
)
from bisheng.knowledge.domain.services.knowledge_space_mutation_executor import (
    UploadExecutionStepCode,
)

TENANT_ID = 42
TOKEN = "generation-1"
STUCK_STEP = UploadExecutionStepCode.BUSINESS_REQUIRED[0]


@pytest.fixture
async def engine() -> AsyncEngine:
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
    state: str = KnowledgeSpaceFileChangeExecutionState.APPLYING,
    token: str | None = TOKEN,
    attempts: int = 0,
    update_time: datetime | None = None,
    with_steps: bool = True,
) -> int:
    async with AsyncSession(bind=engine, expire_on_commit=False) as session, session.begin():
        request = KnowledgeSpaceFileChangeRequest(
            tenant_id=TENANT_ID,
            space_id=152,
            action=KnowledgeSpaceFileChangeAction.UPLOAD,
            resource_type=KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE,
            applicant_user_id=150025,
            business_key=f"knowledge-space-change:exhaustion:{state}:{attempts}",
            request_fingerprint=f"exhaustion-{state}-{attempts}",
            execution_state=state,
            execution_token=token,
            update_time=update_time or datetime.utcnow(),
        )
        session.add(request)
        await session.flush()
        if with_steps:
            for code in UploadExecutionStepCode.BUSINESS_REQUIRED:
                session.add(
                    KnowledgeSpaceFileChangeExecutionStep(
                        tenant_id=TENANT_ID,
                        request_id=int(request.id),
                        step_code=code,
                        attempt_token=str(token),
                        idempotency_key=f"f046:{request.id}:{code}",
                        attempt_count=attempts if code == STUCK_STEP else 0,
                    )
                )
    return int(request.id)


async def _steps(engine: AsyncEngine, request_id: int) -> dict[str, KnowledgeSpaceFileChangeExecutionStep]:
    async with AsyncSession(bind=engine) as session:
        rows = (
            await session.exec(
                select(KnowledgeSpaceFileChangeExecutionStep).where(
                    KnowledgeSpaceFileChangeExecutionStep.request_id == request_id
                )
            )
        ).all()
    return {row.step_code: row for row in rows}


def _coordinator(engine: AsyncEngine) -> KnowledgeSpaceFileChangeExecutionCoordinator:
    return KnowledgeSpaceFileChangeExecutionCoordinator(session_factory=_session_factory(engine))


def _identity(request_id: int) -> ExecutionIdentity:
    return ExecutionIdentity(tenant_id=TENANT_ID, request_id=request_id, execution_token=TOKEN)


# 1. The dispatch budget


async def test_a_step_that_spent_its_budget_is_retired_instead_of_dispatched(engine) -> None:
    request_id = await _seed(engine, attempts=MAX_STEP_DISPATCH_ATTEMPTS)
    dispatcher = AsyncMock(side_effect=lambda context: context.task_id)

    dispatched = await _coordinator(engine).dispatch_ready_steps(
        identity=_identity(request_id),
        dispatcher=dispatcher,
    )

    assert STUCK_STEP not in dispatched
    dispatcher.assert_not_awaited()
    step = (await _steps(engine, request_id))[STUCK_STEP]
    assert step.state == KnowledgeSpaceFileChangeExecutionStepState.FAILED
    assert str(MAX_STEP_DISPATCH_ATTEMPTS) in (step.error_summary or "")


async def test_retiring_the_step_lets_the_request_reach_failed(engine) -> None:
    """The exit the livelock never had: a failed step ends the whole request."""

    request_id = await _seed(engine, attempts=MAX_STEP_DISPATCH_ATTEMPTS)
    coordinator = _coordinator(engine)
    identity = _identity(request_id)

    await coordinator.dispatch_ready_steps(identity=identity, dispatcher=AsyncMock())
    status = await coordinator.reconcile(identity=identity)

    assert status == ExecutionReconcileStatus.FAILED
    async with AsyncSession(bind=engine) as session:
        request = await session.get(KnowledgeSpaceFileChangeRequest, request_id)
    assert request.execution_state == KnowledgeSpaceFileChangeExecutionState.FAILED


async def test_a_step_below_the_budget_still_dispatches(engine) -> None:
    """A step that is merely retrying must not be killed off early."""

    request_id = await _seed(engine, attempts=MAX_STEP_DISPATCH_ATTEMPTS - 1)
    dispatcher = AsyncMock(side_effect=lambda context: context.task_id)

    dispatched = await _coordinator(engine).dispatch_ready_steps(
        identity=_identity(request_id),
        dispatcher=dispatcher,
    )

    assert STUCK_STEP in dispatched
    assert (await _steps(engine, request_id))[STUCK_STEP].state == (
        KnowledgeSpaceFileChangeExecutionStepState.DISPATCHED
    )


# 2. The watchdog scan


async def _candidates(engine: AsyncEngine, *, heartbeat_before: datetime):
    async with AsyncSession(bind=engine) as session:
        candidates, _ = await KnowledgeSpaceFileChangeCompensationRepository(session).list_watchdog_candidates(
            tenant_id=TENANT_ID,
            after_request_id=0,
            heartbeat_before=heartbeat_before,
            limit=50,
        )
    return candidates


async def test_a_stale_queued_request_is_a_watchdog_candidate(engine) -> None:
    stale = datetime.utcnow() - timedelta(hours=6)
    request_id = await _seed(
        engine,
        state=KnowledgeSpaceFileChangeExecutionState.QUEUED,
        token=None,
        update_time=stale,
        with_steps=False,
    )

    candidates = await _candidates(engine, heartbeat_before=datetime.utcnow() - timedelta(minutes=15))

    assert [candidate.request_id for candidate in candidates] == [request_id]
    assert candidates[0].execution_state == KnowledgeSpaceFileChangeExecutionState.QUEUED
    # No token exists yet — `begin_execution` mints it — so the scan must not
    # require one, which is exactly what used to filter these rows out.
    assert candidates[0].execution_token is None


async def test_a_queued_request_within_the_timeout_is_left_alone(engine) -> None:
    await _seed(
        engine,
        state=KnowledgeSpaceFileChangeExecutionState.QUEUED,
        token=None,
        update_time=datetime.utcnow(),
        with_steps=False,
    )

    assert await _candidates(engine, heartbeat_before=datetime.utcnow() - timedelta(minutes=15)) == []


async def test_a_stale_applying_request_is_still_a_candidate(engine) -> None:
    """Widening the scan must not lose the case it already covered."""

    stale = datetime.utcnow() - timedelta(hours=6)
    request_id = await _seed(engine, update_time=stale)

    candidates = await _candidates(engine, heartbeat_before=datetime.utcnow() - timedelta(minutes=15))

    assert [candidate.request_id for candidate in candidates] == [request_id]
    assert candidates[0].execution_token == TOKEN
    assert candidates[0].execution_state == KnowledgeSpaceFileChangeExecutionState.APPLYING


# 3. Routing the two kinds of candidate


async def test_a_stranded_queued_request_is_re_driven_not_watchdogged() -> None:
    """Its work is still owed: the approval was granted, so begin it again."""

    from bisheng.knowledge.domain.repositories.knowledge_space_file_change_compensation_repository import (
        ExecutionWatchdogCandidate,
    )
    from bisheng.knowledge.domain.services.knowledge_space_file_change_compensation_service import (
        CompensationPage,
    )
    from bisheng.worker.knowledge import file_change_tasks

    page = CompensationPage(
        items=[
            ExecutionWatchdogCandidate(
                request_id=5,
                execution_token=None,
                execution_state=KnowledgeSpaceFileChangeExecutionState.QUEUED,
            ),
            ExecutionWatchdogCandidate(
                request_id=6,
                execution_token=TOKEN,
                execution_state=KnowledgeSpaceFileChangeExecutionState.APPLYING,
            ),
        ],
        has_more=False,
        next_after_id=6,
    )
    service = AsyncMock()
    service.list_watchdog_page = AsyncMock(return_value=page)

    with (
        patch.object(file_change_tasks, "_build_compensation_service", return_value=service),
        patch.object(file_change_tasks.coordinate_file_change_execution, "apply_async") as coordinate,
        patch.object(file_change_tasks.watchdog_file_change_execution, "apply_async") as watchdog,
    ):
        result = await file_change_tasks._watchdog_tenant_page_async(tenant_id=TENANT_ID, after_request_id=0)

    assert result["dispatched"] == 2
    assert coordinate.call_args.kwargs["kwargs"] == {"request_id": 5}
    assert watchdog.call_args.kwargs["kwargs"] == {"request_id": 6, "execution_token": TOKEN}
