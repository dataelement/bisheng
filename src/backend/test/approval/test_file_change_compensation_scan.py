from __future__ import annotations

from datetime import datetime, timedelta

import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_instance import (
    ApprovalInstance,
    ApprovalInstanceStatus,
    ApprovalOutbox,
    ApprovalOutboxStatus,
)
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
from bisheng.knowledge.domain.services.knowledge_space_file_change_scenario_handler import (
    FILE_CHANGE_SCENARIO_CODE,
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
        ApprovalInstance.__table__,
        ApprovalOutbox.__table__,
        KnowledgeSpaceUploadStage.__table__,
        KnowledgeSpaceFileChangeRequest.__table__,
        KnowledgeSpaceFileChangeFootprint.__table__,
        KnowledgeSpaceFileChangeExecutionStep.__table__,
    ]
    async with engine.begin() as connection:
        await connection.run_sync(lambda conn: SQLModel.metadata.create_all(conn, tables=tables))
    yield engine
    await engine.dispose()


def _instance(*, row_id: int, tenant_id: int, status: str, scenario_code: str = FILE_CHANGE_SCENARIO_CODE):
    return ApprovalInstance(
        id=row_id,
        tenant_id=tenant_id,
        scenario_code=scenario_code,
        scenario_name="file change",
        handler_key=scenario_code,
        business_key=f"request:{row_id}",
        business_resource_type="knowledge_space_file_change",
        business_resource_id=str(row_id),
        business_name=f"request-{row_id}",
        applicant_user_id=7,
        applicant_user_name="applicant",
        status=status,
    )


def _request(
    *,
    row_id: int,
    tenant_id: int,
    instance_id: int,
    action: str = KnowledgeSpaceFileChangeAction.RENAME,
    execution_state: str = KnowledgeSpaceFileChangeExecutionState.APPLYING,
    execution_token: str = "generation-1",
    cleanup_state: str = KnowledgeSpaceFileChangeCleanupState.NONE,
    upload_stage_id: int | None = None,
    execution_checkpoint: dict | None = None,
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
        approval_instance_id=instance_id,
        upload_stage_id=upload_stage_id,
        execution_state=execution_state,
        execution_token=execution_token,
        cleanup_state=cleanup_state,
        execution_checkpoint=execution_checkpoint or {},
    )


def _outbox(
    *,
    row_id: int,
    tenant_id: int,
    instance_id: int,
    status: str = ApprovalOutboxStatus.DEFERRED,
    token: str = "generation-1",
    deadline: datetime | None = None,
    heartbeat: datetime | None = None,
):
    return ApprovalOutbox(
        id=row_id,
        tenant_id=tenant_id,
        instance_id=instance_id,
        handler_key=FILE_CHANGE_SCENARIO_CODE,
        status=status,
        execution_token=token,
        deferred_deadline=deadline,
        heartbeat_at=heartbeat,
    )


def _footprint(*, row_id: int, tenant_id: int, request_id: int):
    return KnowledgeSpaceFileChangeFootprint(
        id=row_id,
        tenant_id=tenant_id,
        request_id=request_id,
        space_id=8,
        resource_type=KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE,
        resource_id=500 + request_id,
        path_root=f"/resource-{request_id}/",
        lock_scope=KnowledgeSpaceFileChangeLockScope.EXACT,
    )


async def test_deferred_watchdog_scan_is_tenant_scenario_status_and_deadline_bound(compensation_engine):
    now = datetime.utcnow()
    async with AsyncSession(compensation_engine) as session:
        session.add_all(
            [
                _instance(row_id=1, tenant_id=11, status=ApprovalInstanceStatus.EXECUTING),
                _request(row_id=101, tenant_id=11, instance_id=1),
                _outbox(
                    row_id=201,
                    tenant_id=11,
                    instance_id=1,
                    deadline=now - timedelta(seconds=1),
                    heartbeat=now,
                ),
                _instance(row_id=2, tenant_id=11, status=ApprovalInstanceStatus.EXECUTING),
                _request(row_id=102, tenant_id=11, instance_id=2),
                _outbox(
                    row_id=202,
                    tenant_id=11,
                    instance_id=2,
                    deadline=now + timedelta(hours=1),
                    heartbeat=now,
                ),
                _instance(row_id=3, tenant_id=12, status=ApprovalInstanceStatus.EXECUTING),
                _request(row_id=103, tenant_id=12, instance_id=3),
                _outbox(
                    row_id=203,
                    tenant_id=12,
                    instance_id=3,
                    deadline=now - timedelta(seconds=1),
                ),
                _instance(row_id=4, tenant_id=11, status=ApprovalInstanceStatus.EXECUTED),
                _request(row_id=104, tenant_id=11, instance_id=4),
                _outbox(
                    row_id=204,
                    tenant_id=11,
                    instance_id=4,
                    deadline=now - timedelta(seconds=1),
                ),
            ]
        )
        await session.commit()

        rows, has_more = await KnowledgeSpaceFileChangeCompensationRepository(
            session
        ).list_deferred_watchdog_candidates(
            tenant_id=11,
            scenario_code=FILE_CHANGE_SCENARIO_CODE,
            after_outbox_id=0,
            now=now,
            heartbeat_before=now - timedelta(minutes=15),
            limit=1,
        )

    assert not has_more
    assert [(row.outbox_id, row.request_id, row.execution_token) for row in rows] == [(201, 101, "generation-1")]


async def test_step_scan_honors_due_retry_and_bounded_id_cursor(compensation_engine):
    now = datetime.utcnow()
    async with AsyncSession(compensation_engine) as session:
        session.add_all(
            [
                _instance(row_id=11, tenant_id=11, status=ApprovalInstanceStatus.EXECUTING),
                _request(row_id=111, tenant_id=11, instance_id=11),
                _outbox(row_id=211, tenant_id=11, instance_id=11, deadline=now + timedelta(hours=1)),
                KnowledgeSpaceFileChangeExecutionStep(
                    id=301,
                    tenant_id=11,
                    request_id=111,
                    step_code="rename.index_shadow",
                    attempt_token="generation-1",
                    idempotency_key="f046:111:rename.index_shadow",
                    state=KnowledgeSpaceFileChangeExecutionStepState.DISPATCHED,
                    next_retry_at=now - timedelta(seconds=1),
                ),
                KnowledgeSpaceFileChangeExecutionStep(
                    id=302,
                    tenant_id=11,
                    request_id=111,
                    step_code="rename.db_cutover",
                    attempt_token="generation-1",
                    idempotency_key="f046:111:rename.db_cutover",
                    state=KnowledgeSpaceFileChangeExecutionStepState.FAILED,
                    next_retry_at=now + timedelta(hours=1),
                ),
            ]
        )
        await session.commit()
        repository = KnowledgeSpaceFileChangeCompensationRepository(session)
        first, has_more = await repository.list_step_recovery_candidates(
            tenant_id=11,
            scenario_code=FILE_CHANGE_SCENARIO_CODE,
            after_step_id=0,
            now=now,
            limit=1,
        )
        second, second_has_more = await repository.list_step_recovery_candidates(
            tenant_id=11,
            scenario_code=FILE_CHANGE_SCENARIO_CODE,
            after_step_id=301,
            now=now,
            limit=1,
        )

    assert has_more is False
    assert [(row.step_id, row.request_id, row.execution_state) for row in first] == [
        (301, 111, KnowledgeSpaceFileChangeExecutionState.APPLYING)
    ]
    assert second == []
    assert second_has_more is False


async def test_cleanup_scan_only_returns_terminal_upload_and_active_delete_purge(compensation_engine):
    now = datetime.utcnow()
    async with AsyncSession(compensation_engine) as session:
        session.add_all(
            [
                _instance(row_id=21, tenant_id=11, status=ApprovalInstanceStatus.REJECTED),
                KnowledgeSpaceUploadStage(
                    id=401,
                    upload_id="opaque-upload",
                    tenant_id=11,
                    space_id=8,
                    uploader_user_id=7,
                    object_name="internal/object",
                    file_name="report.pdf",
                    file_size=100,
                    content_hash="hash",
                    state=KnowledgeSpaceUploadStageState.ATTACHED,
                    expire_at=now + timedelta(days=1),
                ),
                _request(
                    row_id=121,
                    tenant_id=11,
                    instance_id=21,
                    action=KnowledgeSpaceFileChangeAction.UPLOAD,
                    execution_state=KnowledgeSpaceFileChangeExecutionState.NOT_STARTED,
                    execution_token="",
                    cleanup_state=KnowledgeSpaceFileChangeCleanupState.PENDING,
                    upload_stage_id=401,
                ),
                _instance(row_id=22, tenant_id=11, status=ApprovalInstanceStatus.EXECUTING),
                _outbox(
                    row_id=302,
                    tenant_id=11,
                    instance_id=22,
                    token="delete-generation",
                ),
                _request(
                    row_id=122,
                    tenant_id=11,
                    instance_id=22,
                    action=KnowledgeSpaceFileChangeAction.DELETE,
                    execution_state=KnowledgeSpaceFileChangeExecutionState.APPLYING,
                    execution_token="delete-generation",
                ),
                KnowledgeSpaceFileChangeExecutionStep(
                    id=402,
                    tenant_id=11,
                    request_id=122,
                    step_code="delete.minio_purge",
                    attempt_token="delete-generation",
                    idempotency_key="f046:122:delete.minio_purge",
                    state=KnowledgeSpaceFileChangeExecutionStepState.FAILED,
                    next_retry_at=now - timedelta(seconds=1),
                ),
                _instance(row_id=23, tenant_id=11, status=ApprovalInstanceStatus.EXECUTE_FAILED),
                KnowledgeSpaceUploadStage(
                    id=403,
                    upload_id="failed-upload",
                    tenant_id=11,
                    space_id=8,
                    uploader_user_id=7,
                    object_name="internal/failed-object",
                    file_name="failed.pdf",
                    file_size=100,
                    content_hash="failed-hash",
                    state=KnowledgeSpaceUploadStageState.CLEANUP_PENDING,
                    expire_at=now + timedelta(days=1),
                ),
                _request(
                    row_id=123,
                    tenant_id=11,
                    instance_id=23,
                    action=KnowledgeSpaceFileChangeAction.UPLOAD,
                    execution_state=KnowledgeSpaceFileChangeExecutionState.FAILED,
                    cleanup_state=KnowledgeSpaceFileChangeCleanupState.PENDING,
                    upload_stage_id=403,
                ),
                _instance(row_id=24, tenant_id=11, status=ApprovalInstanceStatus.EXECUTE_FAILED),
                KnowledgeSpaceUploadStage(
                    id=404,
                    upload_id="failed-not-requested-cleanup",
                    tenant_id=11,
                    space_id=8,
                    uploader_user_id=7,
                    object_name="internal/retained-object",
                    file_name="retained.pdf",
                    file_size=100,
                    content_hash="retained-hash",
                    state=KnowledgeSpaceUploadStageState.ATTACHED,
                    expire_at=now + timedelta(days=1),
                ),
                _request(
                    row_id=124,
                    tenant_id=11,
                    instance_id=24,
                    action=KnowledgeSpaceFileChangeAction.UPLOAD,
                    execution_state=KnowledgeSpaceFileChangeExecutionState.FAILED,
                    cleanup_state=KnowledgeSpaceFileChangeCleanupState.NONE,
                    upload_stage_id=404,
                ),
                _instance(row_id=25, tenant_id=11, status=ApprovalInstanceStatus.EXECUTED),
                _request(
                    row_id=125,
                    tenant_id=11,
                    instance_id=25,
                    action=KnowledgeSpaceFileChangeAction.RENAME,
                    execution_state=KnowledgeSpaceFileChangeExecutionState.APPLIED,
                    execution_token="rename-generation",
                    execution_checkpoint={
                        "mutation_transition_active": True,
                        "mutation_transition_phase": "new_view",
                    },
                ),
                _footprint(row_id=601, tenant_id=11, request_id=125),
            ]
        )
        await session.commit()

        rows, has_more, next_after_id = await KnowledgeSpaceFileChangeCompensationRepository(
            session
        ).list_cleanup_candidates(
            tenant_id=11,
            scenario_code=FILE_CHANGE_SCENARIO_CODE,
            after_request_id=0,
            now=now,
            limit=10,
        )

    assert not has_more
    assert next_after_id == 125
    assert [(row.request_id, row.kind) for row in rows] == [
        (121, "stage"),
        (122, "delete_purge"),
        (123, "stage"),
        (125, "mutation_cleanup"),
    ]
    assert rows[0].upload_id == "opaque-upload"
    assert rows[0].terminal_action == ApprovalInstanceStatus.REJECTED
    assert rows[1].execution_token == "delete-generation"
    assert rows[2].upload_id == "failed-upload"
    assert rows[2].terminal_action == ApprovalInstanceStatus.EXECUTE_FAILED
    assert rows[3].execution_token == "rename-generation"


async def test_cleanup_scan_inactive_history_does_not_hide_active_projection(compensation_engine):
    now = datetime.utcnow()
    async with AsyncSession(compensation_engine) as session:
        session.add_all(
            [
                _instance(row_id=31, tenant_id=11, status=ApprovalInstanceStatus.EXECUTED),
                _request(
                    row_id=130,
                    tenant_id=11,
                    instance_id=31,
                    execution_state=KnowledgeSpaceFileChangeExecutionState.APPLIED,
                    execution_checkpoint={"mutation_transition_active": False},
                ),
                _instance(row_id=32, tenant_id=11, status=ApprovalInstanceStatus.EXECUTED),
                _request(
                    row_id=131,
                    tenant_id=11,
                    instance_id=32,
                    execution_state=KnowledgeSpaceFileChangeExecutionState.APPLIED,
                    execution_checkpoint={"mutation_transition_active": True},
                ),
                _footprint(row_id=602, tenant_id=11, request_id=131),
            ]
        )
        await session.commit()

        rows, has_more, next_after_id = await KnowledgeSpaceFileChangeCompensationRepository(
            session
        ).list_cleanup_candidates(
            tenant_id=11,
            scenario_code=FILE_CHANGE_SCENARIO_CODE,
            after_request_id=0,
            now=now,
            limit=1,
        )

    assert [(row.request_id, row.kind) for row in rows] == [(131, "mutation_cleanup")]
    assert has_more is False
    assert next_after_id == 131


async def test_cleanup_scan_empty_filtered_page_advances_raw_cursor(compensation_engine):
    now = datetime.utcnow()
    async with AsyncSession(compensation_engine) as session:
        session.add_all(
            [
                _instance(row_id=33, tenant_id=11, status=ApprovalInstanceStatus.EXECUTED),
                _request(
                    row_id=140,
                    tenant_id=11,
                    instance_id=33,
                    execution_state=KnowledgeSpaceFileChangeExecutionState.APPLIED,
                    execution_checkpoint={"mutation_transition_active": False},
                ),
                _footprint(row_id=603, tenant_id=11, request_id=140),
                _instance(row_id=34, tenant_id=11, status=ApprovalInstanceStatus.EXECUTED),
                _request(
                    row_id=141,
                    tenant_id=11,
                    instance_id=34,
                    execution_state=KnowledgeSpaceFileChangeExecutionState.APPLIED,
                    execution_checkpoint={"mutation_transition_active": True},
                ),
                _footprint(row_id=604, tenant_id=11, request_id=141),
            ]
        )
        await session.commit()
        repository = KnowledgeSpaceFileChangeCompensationRepository(session)

        first_rows, first_has_more, first_cursor = await repository.list_cleanup_candidates(
            tenant_id=11,
            scenario_code=FILE_CHANGE_SCENARIO_CODE,
            after_request_id=0,
            now=now,
            limit=1,
        )
        second_rows, second_has_more, second_cursor = await repository.list_cleanup_candidates(
            tenant_id=11,
            scenario_code=FILE_CHANGE_SCENARIO_CODE,
            after_request_id=first_cursor,
            now=now,
            limit=1,
        )

    assert first_rows == []
    assert first_has_more is True
    assert first_cursor == 140
    assert [(row.request_id, row.kind) for row in second_rows] == [(141, "mutation_cleanup")]
    assert second_has_more is False
    assert second_cursor == 141


async def test_stage_lifecycle_scan_returns_bound_attaching_and_expired_unbound_rows(compensation_engine):
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
                    upload_id="expired-attached-state",
                    tenant_id=11,
                    space_id=8,
                    uploader_user_id=7,
                    object_name="internal/attached",
                    file_name="attached.pdf",
                    file_size=100,
                    content_hash="attached-hash",
                    state=KnowledgeSpaceUploadStageState.ATTACHED,
                    expire_at=now - timedelta(seconds=1),
                ),
                KnowledgeSpaceUploadStage(
                    id=503,
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
                KnowledgeSpaceUploadStage(
                    id=504,
                    upload_id="other-tenant-orphan",
                    tenant_id=12,
                    space_id=8,
                    uploader_user_id=7,
                    object_name="internal/other-tenant",
                    file_name="other.pdf",
                    file_size=100,
                    content_hash="other-hash",
                    state=KnowledgeSpaceUploadStageState.UPLOADED,
                    expire_at=now - timedelta(seconds=1),
                ),
                KnowledgeSpaceUploadStage(
                    id=505,
                    upload_id="bound-attaching",
                    tenant_id=11,
                    space_id=8,
                    uploader_user_id=7,
                    object_name="internal/bound-attaching",
                    file_name="bound-attaching.pdf",
                    file_size=100,
                    content_hash="bound-attaching-hash",
                    state=KnowledgeSpaceUploadStageState.ATTACHING,
                    expire_at=now + timedelta(days=29),
                ),
            ]
        )
        await session.flush()
        session.add(
            KnowledgeSpaceFileChangeRequest(
                id=601,
                tenant_id=11,
                space_id=8,
                action=KnowledgeSpaceFileChangeAction.UPLOAD,
                resource_type=KnowledgeSpaceFileChangeResourceType.STAGED_UPLOAD,
                applicant_user_id=7,
                upload_stage_id=505,
            )
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
    assert [(row.stage_id, row.upload_id) for row in rows] == [
        (501, "expired-orphan"),
        (505, "bound-attaching"),
    ]
