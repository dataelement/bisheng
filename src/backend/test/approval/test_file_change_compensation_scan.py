from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import current_tenant_id
from bisheng.knowledge.domain.models.knowledge_space_file_change_execution_step import (
    KnowledgeSpaceFileChangeExecutionStep,
    KnowledgeSpaceFileChangeExecutionStepState,
)
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeAction,
    KnowledgeSpaceFileChangeCleanupState,
    KnowledgeSpaceFileChangeExecutionState,
    KnowledgeSpaceFileChangeFootprint,
    KnowledgeSpaceFileChangeLockScope,
    KnowledgeSpaceFileChangeRequest,
    KnowledgeSpaceFileChangeResourceType,
)
from bisheng.knowledge.domain.models.knowledge_space_upload_stage import (
    KnowledgeSpaceUploadStage,
    KnowledgeSpaceUploadStageState,
)
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_compensation_repository import (
    KnowledgeSpaceFileChangeCompensationRepository,
)
from bisheng.knowledge.domain.services.knowledge_space_file_change_execution_coordinator import (
    ExecutionIdentity,
    KnowledgeSpaceFileChangeExecutionCoordinator,
)
from bisheng.knowledge.domain.services.knowledge_space_mutation_executor import (
    DELETE_PHASE_CHECKPOINT_KEY,
    DELETE_PHASE_COMPLETED,
    DELETE_PHASE_PURGE_FAILED,
    DELETE_PHASE_PURGING,
    DeleteExecutionStepCode,
)


@pytest_asyncio.fixture(autouse=True)
async def compensation_tenant_context():
    token = current_tenant_id.set(11)
    try:
        yield
    finally:
        current_tenant_id.reset(token)


@pytest_asyncio.fixture
async def compensation_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        KnowledgeSpaceUploadStage.__table__,
        KnowledgeSpaceFileChangeRequest.__table__,
        KnowledgeSpaceFileChangeFootprint.__table__,
        KnowledgeSpaceFileChangeExecutionStep.__table__,
    ]
    async with engine.begin() as connection:
        await connection.run_sync(lambda conn: SQLModel.metadata.create_all(conn, tables=tables))
    yield engine
    await engine.dispose()


def _request(
    *,
    row_id: int,
    tenant_id: int = 11,
    action: str = KnowledgeSpaceFileChangeAction.RENAME,
    execution_state: str = KnowledgeSpaceFileChangeExecutionState.APPLYING,
    execution_token: str | None = "generation-1",
    cleanup_state: str = KnowledgeSpaceFileChangeCleanupState.NONE,
    upload_stage_id: int | None = None,
    execution_checkpoint: dict | None = None,
    result_snapshot: dict | None = None,
    update_time: datetime | None = None,
):
    return KnowledgeSpaceFileChangeRequest(
        id=row_id,
        tenant_id=tenant_id,
        space_id=8,
        action=action,
        resource_type=(
            KnowledgeSpaceFileChangeResourceType.STAGED_UPLOAD
            if action == KnowledgeSpaceFileChangeAction.UPLOAD
            else KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE
        ),
        resource_id=None if action == KnowledgeSpaceFileChangeAction.UPLOAD else 500 + row_id,
        applicant_user_id=7,
        business_key=f"request:{row_id}",
        request_fingerprint=f"fingerprint:{row_id}",
        upload_stage_id=upload_stage_id,
        execution_state=execution_state,
        execution_token=execution_token,
        cleanup_state=cleanup_state,
        execution_checkpoint=execution_checkpoint or {},
        result_snapshot=result_snapshot or {},
        update_time=update_time,
    )


def _step(
    *,
    row_id: int,
    request_id: int,
    code: str,
    state: str,
    token: str = "generation-1",
    next_retry_at: datetime | None = None,
):
    return KnowledgeSpaceFileChangeExecutionStep(
        id=row_id,
        tenant_id=11,
        request_id=request_id,
        step_code=code,
        attempt_token=token,
        idempotency_key=f"f046:{request_id}:{code}",
        state=state,
        next_retry_at=next_retry_at,
    )


def _footprint(*, row_id: int, request_id: int):
    return KnowledgeSpaceFileChangeFootprint(
        id=row_id,
        tenant_id=11,
        request_id=request_id,
        space_id=8,
        resource_type=KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE,
        resource_id=500 + request_id,
        path_root=f"/resource-{request_id}/",
        lock_scope=KnowledgeSpaceFileChangeLockScope.EXACT,
    )


def test_compensation_scan_source_has_no_approval_or_outbox_dependency():
    repository_path = (
        Path(__file__).resolve().parents[2]
        / "bisheng"
        / "knowledge"
        / "domain"
        / "repositories"
        / "knowledge_space_file_change_compensation_repository.py"
    )
    source = repository_path.read_text(encoding="utf-8")
    forbidden = (
        "bisheng.approval",
        "ApprovalInstance",
        "ApprovalOutbox",
        "ApprovalOutboxStatus",
        "scenario_code",
        "outbox_id",
        "instance_id",
    )
    for fragment in forbidden:
        assert fragment not in source


async def test_watchdog_candidates_come_only_from_stale_current_knowledge_requests(compensation_engine):
    now = datetime.utcnow()
    async with AsyncSession(compensation_engine) as session:
        session.add_all(
            [
                _request(row_id=101, update_time=now - timedelta(hours=1)),
                _request(
                    row_id=102,
                    execution_state=KnowledgeSpaceFileChangeExecutionState.COMPENSATING,
                    execution_token="generation-2",
                    update_time=now - timedelta(hours=1),
                ),
                _request(row_id=103, update_time=now),
                _request(
                    row_id=104,
                    execution_state=KnowledgeSpaceFileChangeExecutionState.APPLIED,
                    update_time=now - timedelta(hours=1),
                ),
                _request(row_id=105, tenant_id=12, update_time=now - timedelta(hours=1)),
            ]
        )
        await session.commit()

        rows, has_more = await KnowledgeSpaceFileChangeCompensationRepository(
            session
        ).list_watchdog_candidates(
            tenant_id=11,
            after_request_id=0,
            heartbeat_before=now - timedelta(minutes=15),
            limit=10,
        )

    assert not has_more
    assert [(row.request_id, row.execution_token) for row in rows] == [
        (101, "generation-1"),
        (102, "generation-2"),
    ]


async def test_step_recovery_scan_uses_current_request_token_and_due_step_cursor(compensation_engine):
    now = datetime.utcnow()
    async with AsyncSession(compensation_engine) as session:
        session.add_all(
            [
                _request(row_id=111),
                _step(
                    row_id=301,
                    request_id=111,
                    code="rename.index_shadow",
                    state=KnowledgeSpaceFileChangeExecutionStepState.DISPATCHED,
                    next_retry_at=now - timedelta(seconds=1),
                ),
                _step(
                    row_id=302,
                    request_id=111,
                    code="rename.db_cutover",
                    state=KnowledgeSpaceFileChangeExecutionStepState.FAILED,
                    token="old-generation",
                    next_retry_at=now - timedelta(seconds=1),
                ),
                _step(
                    row_id=303,
                    request_id=111,
                    code="rename.verify",
                    state=KnowledgeSpaceFileChangeExecutionStepState.FAILED,
                    next_retry_at=now + timedelta(hours=1),
                ),
            ]
        )
        await session.commit()
        rows, has_more = await KnowledgeSpaceFileChangeCompensationRepository(
            session
        ).list_step_recovery_candidates(
            tenant_id=11,
            after_step_id=0,
            now=now,
            limit=10,
        )

    assert not has_more
    assert [
        (row.step_id, row.request_id, row.execution_token, row.execution_state) for row in rows
    ] == [(301, 111, "generation-1", KnowledgeSpaceFileChangeExecutionState.APPLYING)]
    assert not hasattr(rows[0], "instance_id")
    assert not hasattr(rows[0], "outbox_id")


async def test_cleanup_candidates_use_business_state_step_and_footprint_only(compensation_engine):
    now = datetime.utcnow()
    async with AsyncSession(compensation_engine) as session:
        session.add_all(
            [
                KnowledgeSpaceUploadStage(
                    id=401,
                    upload_id="closed-upload",
                    tenant_id=11,
                    space_id=8,
                    uploader_user_id=7,
                    object_name="internal/closed",
                    file_name="closed.pdf",
                    file_size=100,
                    content_hash="closed-hash",
                    state=KnowledgeSpaceUploadStageState.CLEANUP_PENDING,
                    expire_at=now + timedelta(days=1),
                ),
                _request(
                    row_id=121,
                    action=KnowledgeSpaceFileChangeAction.UPLOAD,
                    execution_state=KnowledgeSpaceFileChangeExecutionState.CLOSED,
                    execution_token=None,
                    cleanup_state=KnowledgeSpaceFileChangeCleanupState.PENDING,
                    upload_stage_id=401,
                    result_snapshot={"decision_action": "rejected"},
                ),
                _request(
                    row_id=122,
                    action=KnowledgeSpaceFileChangeAction.DELETE,
                    execution_checkpoint={
                        DELETE_PHASE_CHECKPOINT_KEY: DELETE_PHASE_PURGING,
                        "deletion_cutover_active": True,
                    },
                ),
                _step(
                    row_id=402,
                    request_id=122,
                    code=DeleteExecutionStepCode.MINIO,
                    state=KnowledgeSpaceFileChangeExecutionStepState.FAILED,
                    next_retry_at=now - timedelta(seconds=1),
                ),
                _request(
                    row_id=123,
                    execution_state=KnowledgeSpaceFileChangeExecutionState.APPLIED,
                    execution_checkpoint={"mutation_transition_active": True},
                ),
                _footprint(row_id=601, request_id=123),
            ]
        )
        await session.commit()

        rows, has_more, next_after_id = await KnowledgeSpaceFileChangeCompensationRepository(
            session
        ).list_cleanup_candidates(
            tenant_id=11,
            after_request_id=0,
            now=now,
            limit=10,
        )

    assert not has_more
    assert next_after_id == 123
    assert [(row.request_id, row.kind) for row in rows] == [
        (121, "stage"),
        (122, "delete_purge"),
        (123, "mutation_cleanup"),
    ]
    assert rows[0].terminal_action == "rejected"
    assert rows[1].execution_token == "generation-1"


async def test_expired_orphan_stage_scan_remains_knowledge_owned(compensation_engine):
    now = datetime.utcnow()
    async with AsyncSession(compensation_engine) as session:
        session.add_all(
            [
                KnowledgeSpaceUploadStage(
                    id=501,
                    upload_id="expired-orphan",
                    tenant_id=11,
                    space_id=8,
                    uploader_user_id=7,
                    object_name="internal/orphan",
                    file_name="orphan.pdf",
                    file_size=100,
                    content_hash="orphan-hash",
                    state=KnowledgeSpaceUploadStageState.UPLOADED,
                    expire_at=now - timedelta(seconds=1),
                ),
                KnowledgeSpaceUploadStage(
                    id=502,
                    upload_id="future-orphan",
                    tenant_id=11,
                    space_id=8,
                    uploader_user_id=7,
                    object_name="internal/future",
                    file_name="future.pdf",
                    file_size=100,
                    content_hash="future-hash",
                    state=KnowledgeSpaceUploadStageState.UPLOADED,
                    expire_at=now + timedelta(hours=1),
                ),
            ]
        )
        await session.commit()
        rows, has_more = await KnowledgeSpaceFileChangeCompensationRepository(
            session
        ).list_expired_orphan_stage_candidates(
            tenant_id=11,
            after_stage_id=0,
            now=now,
            limit=10,
        )

    assert not has_more
    assert [(row.stage_id, row.upload_id) for row in rows] == [(501, "expired-orphan")]


async def test_delete_post_cutover_retry_keeps_guard_and_rebinds_every_step(compensation_engine):
    old_token = "delete-generation-1"
    new_token = "delete-generation-2"
    request = _request(
        row_id=201,
        action=KnowledgeSpaceFileChangeAction.DELETE,
        execution_state=KnowledgeSpaceFileChangeExecutionState.FAILED,
        execution_token=old_token,
        execution_checkpoint={
            DELETE_PHASE_CHECKPOINT_KEY: DELETE_PHASE_PURGE_FAILED,
            "deletion_cutover_active": True,
            "failure_reason": "purge failed",
        },
    )
    rows = []
    for index, code in enumerate(DeleteExecutionStepCode.ALL, start=701):
        state = KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED
        if code == DeleteExecutionStepCode.MINIO:
            state = KnowledgeSpaceFileChangeExecutionStepState.FAILED
        rows.append(_step(row_id=index, request_id=201, code=code, state=state, token=old_token))
    async with AsyncSession(compensation_engine) as session:
        session.add_all([request, *rows])
        await session.commit()

    @asynccontextmanager
    async def session_factory():
        async with AsyncSession(compensation_engine) as session:
            yield session

    identity = await KnowledgeSpaceFileChangeExecutionCoordinator(
        session_factory=session_factory,
        execution_token_factory=lambda: new_token,
    ).queue_retry(tenant_id=11, request_id=201)

    assert identity == ExecutionIdentity(tenant_id=11, request_id=201, execution_token=new_token)
    async with AsyncSession(compensation_engine) as session:
        current = await session.get(KnowledgeSpaceFileChangeRequest, 201)
        steps = list(
            (
                await session.exec(
                    select(KnowledgeSpaceFileChangeExecutionStep).where(
                        KnowledgeSpaceFileChangeExecutionStep.request_id == 201
                    )
                )
            ).all()
        )
    assert current is not None
    assert current.execution_state == KnowledgeSpaceFileChangeExecutionState.QUEUED
    assert current.execution_checkpoint[DELETE_PHASE_CHECKPOINT_KEY] == DELETE_PHASE_PURGING
    assert current.execution_checkpoint["deletion_cutover_active"] is True
    assert {step.attempt_token for step in steps} == {new_token}
    failed_purge = next(step for step in steps if step.step_code == DeleteExecutionStepCode.MINIO)
    assert failed_purge.state == KnowledgeSpaceFileChangeExecutionStepState.PENDING


async def test_compensation_recovered_hint_cannot_bypass_authoritative_completion_gate(compensation_engine):
    token = "delete-generation"
    request = _request(
        row_id=202,
        action=KnowledgeSpaceFileChangeAction.DELETE,
        execution_state=KnowledgeSpaceFileChangeExecutionState.COMPENSATING,
        execution_token=token,
        execution_checkpoint={
            DELETE_PHASE_CHECKPOINT_KEY: DELETE_PHASE_COMPLETED,
            "deletion_cutover_active": False,
        },
    )
    rows = [
        _step(
            row_id=index,
            request_id=202,
            code=code,
            state=KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED,
            token=("stale-generation" if code == DeleteExecutionStepCode.MINIO else token),
        )
        for index, code in enumerate(DeleteExecutionStepCode.ALL, start=801)
    ]
    async with AsyncSession(compensation_engine) as session:
        session.add_all([request, *rows])
        await session.commit()

    @asynccontextmanager
    async def session_factory():
        async with AsyncSession(compensation_engine) as session:
            yield session

    coordinator = KnowledgeSpaceFileChangeExecutionCoordinator(session_factory=session_factory)
    processed = await coordinator.finish_compensation(
        identity=ExecutionIdentity(tenant_id=11, request_id=202, execution_token=token),
        recovered=True,
    )

    assert processed is True
    async with AsyncSession(compensation_engine) as session:
        current = await session.get(KnowledgeSpaceFileChangeRequest, 202)
    assert current is not None
    assert current.execution_state == KnowledgeSpaceFileChangeExecutionState.FAILED
