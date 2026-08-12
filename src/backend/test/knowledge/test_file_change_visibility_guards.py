from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge_space import (
    SpaceFileChangeApproverUnavailableError,
    SpaceFileChangeRequestNotFoundError,
)
from bisheng.core.context.tenant import set_current_tenant_id
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.models.knowledge_space_file_change_execution_step import (
    KnowledgeSpaceFileChangeExecutionStep,
    KnowledgeSpaceFileChangeExecutionStepState,
)
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeAction,
    KnowledgeSpaceFileChangeExecutionState,
    KnowledgeSpaceFileChangeFootprint,
    KnowledgeSpaceFileChangeLockScope,
    KnowledgeSpaceFileChangeRequest,
    KnowledgeSpaceFileChangeResourceType,
)
from bisheng.knowledge.domain.services.knowledge_space_deletion_guard import (
    DELETION_CUTOVER_ACTIVE_CHECKPOINT_KEY,
    KnowledgeSpaceDeletionGuard,
)
from bisheng.knowledge.domain.services.knowledge_space_file_publication_guard import (
    KnowledgeSpaceFilePublicationGuard,
)
from bisheng.knowledge.domain.services.knowledge_space_mutation_executor import (
    UploadExecutionStepCode,
)
from bisheng.knowledge.domain.services.knowledge_space_mutation_read_projection_service import (
    MUTATION_TRANSITION_ACTIVE_CHECKPOINT_KEY,
    MUTATION_TRANSITION_PHASE_CHECKPOINT_KEY,
    MutationReadProjectionService,
)


@pytest.fixture
async def visibility_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            SQLModel.metadata.create_all,
            tables=[
                KnowledgeFile.__table__,
                KnowledgeSpaceFileChangeRequest.__table__,
                KnowledgeSpaceFileChangeFootprint.__table__,
                KnowledgeSpaceFileChangeExecutionStep.__table__,
            ],
        )
    yield engine
    await engine.dispose()


def _session_factory(engine: AsyncEngine):
    @asynccontextmanager
    async def factory():
        async with AsyncSession(bind=engine, expire_on_commit=False) as session:
            yield session

    return factory


async def _seed_upload(
    engine: AsyncEngine,
    *,
    tenant_id: int,
    space_id: int,
    applicant_user_id: int,
    execution_state: str = KnowledgeSpaceFileChangeExecutionState.APPLYING,
    file_status: int = KnowledgeFileStatus.WAITING.value,
    step_states: dict[str, str] | None = None,
    folder_ids: tuple[int, ...] = (),
    fga_only_resource_id: int | None = None,
) -> tuple[int, int]:
    async with AsyncSession(bind=engine, expire_on_commit=False) as session:
        async with session.begin():
            db_file = KnowledgeFile(
                tenant_id=tenant_id,
                user_id=applicant_user_id,
                knowledge_id=space_id,
                file_name=f"tenant-{tenant_id}.pdf",
                file_type=1,
                status=file_status,
            )
            session.add(db_file)
            await session.flush()
            formal_resource_ids = [
                *(
                    {"resource_type": KnowledgeSpaceFileChangeResourceType.FOLDER, "resource_id": folder_id}
                    for folder_id in folder_ids
                ),
                {
                    "resource_type": KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE,
                    "resource_id": int(db_file.id),
                },
            ]
            request = KnowledgeSpaceFileChangeRequest(
                tenant_id=tenant_id,
                space_id=space_id,
                action=KnowledgeSpaceFileChangeAction.UPLOAD,
                resource_type=KnowledgeSpaceFileChangeResourceType.STAGED_UPLOAD,
                applicant_user_id=applicant_user_id,
                approval_instance_id=tenant_id * 1000 + int(db_file.id),
                executed_resource_id=int(db_file.id),
                execution_state=execution_state,
                execution_checkpoint={
                    "formal_resource_ids": formal_resource_ids,
                    "fga_resources": (
                        [{"resource_id": fga_only_resource_id}] if fga_only_resource_id is not None else []
                    ),
                },
            )
            session.add(request)
            await session.flush()
            resolved_step_states = step_states or dict.fromkeys(
                UploadExecutionStepCode.ALL, KnowledgeSpaceFileChangeExecutionStepState.PENDING
            )
            for step_code in UploadExecutionStepCode.ALL:
                session.add(
                    KnowledgeSpaceFileChangeExecutionStep(
                        tenant_id=tenant_id,
                        request_id=int(request.id),
                        step_code=step_code,
                        attempt_token="token-1",
                        idempotency_key=f"f046:{request.id}:{step_code}",
                        state=resolved_step_states[step_code],
                    )
                )
    return int(request.id), int(db_file.id)


async def _set_upload_truth(
    engine: AsyncEngine,
    *,
    request_id: int,
    tenant_id: int,
    request_state: str,
    file_status: int,
    step_states: dict[str, str],
) -> None:
    async with AsyncSession(bind=engine, expire_on_commit=False) as session:
        async with session.begin():
            request = (
                await session.exec(
                    select(KnowledgeSpaceFileChangeRequest).where(
                        KnowledgeSpaceFileChangeRequest.tenant_id == tenant_id,
                        KnowledgeSpaceFileChangeRequest.id == request_id,
                    )
                )
            ).one()
            request.execution_state = request_state
            session.add(request)
            db_file = (
                await session.exec(
                    select(KnowledgeFile).where(
                        KnowledgeFile.tenant_id == tenant_id,
                        KnowledgeFile.id == request.executed_resource_id,
                    )
                )
            ).one()
            db_file.status = file_status
            session.add(db_file)
            steps = list(
                (
                    await session.exec(
                        select(KnowledgeSpaceFileChangeExecutionStep).where(
                            KnowledgeSpaceFileChangeExecutionStep.tenant_id == tenant_id,
                            KnowledgeSpaceFileChangeExecutionStep.request_id == request_id,
                        )
                    )
                ).all()
            )
            for step in steps:
                step.state = step_states[step.step_code]
                session.add(step)


async def _seed_delete(
    engine: AsyncEngine,
    *,
    tenant_id: int,
    space_id: int,
    resource_ids: tuple[int, ...],
    execution_state: str,
    cutover_active: bool,
) -> int:
    async with AsyncSession(bind=engine, expire_on_commit=False) as session:
        async with session.begin():
            request = KnowledgeSpaceFileChangeRequest(
                tenant_id=tenant_id,
                space_id=space_id,
                action=KnowledgeSpaceFileChangeAction.DELETE,
                resource_type=KnowledgeSpaceFileChangeResourceType.FOLDER,
                resource_id=resource_ids[0],
                applicant_user_id=70,
                approval_instance_id=tenant_id * 10000 + resource_ids[0],
                execution_state=execution_state,
                execution_checkpoint={DELETION_CUTOVER_ACTIVE_CHECKPOINT_KEY: cutover_active},
            )
            session.add(request)
            await session.flush()
            for resource_id in resource_ids:
                session.add(
                    KnowledgeSpaceFileChangeFootprint(
                        tenant_id=tenant_id,
                        request_id=int(request.id),
                        space_id=space_id,
                        resource_type=KnowledgeSpaceFileChangeResourceType.FOLDER,
                        resource_id=resource_id,
                        path_root=f"/{resource_id}/",
                        lock_scope=KnowledgeSpaceFileChangeLockScope.SUBTREE,
                    )
                )
    return int(request.id)


async def _seed_mutation_fence(
    engine: AsyncEngine,
    *,
    tenant_id: int,
    source_space_id: int,
    target_space_id: int,
    resource_id: int,
    execution_state: str = KnowledgeSpaceFileChangeExecutionState.APPLYING,
    fence_active: bool = True,
) -> int:
    async with AsyncSession(bind=engine, expire_on_commit=False) as session:
        async with session.begin():
            request = KnowledgeSpaceFileChangeRequest(
                tenant_id=tenant_id,
                space_id=source_space_id,
                action=KnowledgeSpaceFileChangeAction.MOVE,
                resource_type=KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE,
                resource_id=resource_id,
                applicant_user_id=70,
                approval_instance_id=tenant_id * 10000 + resource_id,
                execution_state=execution_state,
                execution_checkpoint={
                    MUTATION_TRANSITION_ACTIVE_CHECKPOINT_KEY: fence_active,
                    MUTATION_TRANSITION_PHASE_CHECKPOINT_KEY: "old_view",
                    "mutation_manifest": {
                        "action": "move",
                        "source_space_id": source_space_id,
                        "target_space_id": target_space_id,
                        "rows": [
                            {
                                "id": resource_id,
                                "file_type": 1,
                                "old_space_id": source_space_id,
                                "new_space_id": target_space_id,
                                "old_name": f"old-{resource_id}.pdf",
                            }
                        ],
                    },
                },
            )
            session.add(request)
            await session.flush()
            for space_id in (source_space_id, target_space_id):
                session.add(
                    KnowledgeSpaceFileChangeFootprint(
                        tenant_id=tenant_id,
                        request_id=int(request.id),
                        space_id=space_id,
                        resource_type=KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE,
                        resource_id=resource_id,
                        path_root=f"/{resource_id}/",
                        lock_scope=KnowledgeSpaceFileChangeLockScope.EXACT,
                    )
                )
    return int(request.id)


async def _seed_rename_projection(
    engine: AsyncEngine,
    *,
    tenant_id: int,
    space_id: int,
    resource_id: int,
    phase: str,
) -> int:
    async with AsyncSession(bind=engine, expire_on_commit=False) as session:
        async with session.begin():
            request = KnowledgeSpaceFileChangeRequest(
                tenant_id=tenant_id,
                space_id=space_id,
                action=KnowledgeSpaceFileChangeAction.RENAME,
                resource_type=KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE,
                resource_id=resource_id,
                applicant_user_id=70,
                approval_instance_id=tenant_id * 10000 + resource_id,
                execution_state=(
                    KnowledgeSpaceFileChangeExecutionState.APPLIED
                    if phase == "new_view"
                    else KnowledgeSpaceFileChangeExecutionState.APPLYING
                ),
                execution_checkpoint={
                    MUTATION_TRANSITION_ACTIVE_CHECKPOINT_KEY: True,
                    MUTATION_TRANSITION_PHASE_CHECKPOINT_KEY: phase,
                    "mutation_manifest": {
                        "action": "rename",
                        "new_name": "new.pdf",
                        "root": {
                            "id": resource_id,
                            "file_type": 1,
                            "old_space_id": space_id,
                            "old_name": "old.pdf",
                        },
                        "rows": [
                            {
                                "id": resource_id,
                                "file_type": 1,
                                "old_space_id": space_id,
                                "old_name": "old.pdf",
                            }
                        ],
                    },
                },
            )
            session.add(request)
            await session.flush()
            session.add(
                KnowledgeSpaceFileChangeFootprint(
                    tenant_id=tenant_id,
                    request_id=int(request.id),
                    space_id=space_id,
                    resource_type=KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE,
                    resource_id=resource_id,
                    path_root=f"/{resource_id}/",
                    lock_scope=KnowledgeSpaceFileChangeLockScope.EXACT,
                )
            )
    return int(request.id)


def _all_steps(state: str) -> dict[str, str]:
    return dict.fromkeys(UploadExecutionStepCode.ALL, state)


async def test_publication_guard_hides_manifest_until_every_authoritative_truth_is_complete(
    visibility_engine,
):
    set_current_tenant_id(42)
    request_id, file_id = await _seed_upload(
        visibility_engine,
        tenant_id=42,
        space_id=8,
        applicant_user_id=7,
        folder_ids=(201, 202),
        fga_only_resource_id=999,
    )
    await _seed_upload(
        visibility_engine,
        tenant_id=99,
        space_id=8,
        applicant_user_id=9,
        folder_ids=(777,),
    )
    guard = KnowledgeSpaceFilePublicationGuard(session_factory=_session_factory(visibility_engine))

    assert await guard.list_unpublished_ids(tenant_id=42, space_ids=[8]) == {201, 202, file_id}
    assert 999 not in await guard.list_unpublished_ids(tenant_id=42, space_ids=[8])
    assert 777 not in await guard.list_unpublished_ids(tenant_id=42, space_ids=[8])

    await _set_upload_truth(
        visibility_engine,
        request_id=request_id,
        tenant_id=42,
        request_state=KnowledgeSpaceFileChangeExecutionState.APPLIED,
        file_status=KnowledgeFileStatus.FAILED.value,
        step_states=_all_steps(KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED),
    )
    assert await guard.list_unpublished_ids(tenant_id=42, space_ids=[8]) == set()

    await _set_upload_truth(
        visibility_engine,
        request_id=request_id,
        tenant_id=42,
        request_state=KnowledgeSpaceFileChangeExecutionState.APPLIED,
        file_status=KnowledgeFileStatus.SUCCESS.value,
        step_states={
            **_all_steps(KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED),
            UploadExecutionStepCode.VECTOR: KnowledgeSpaceFileChangeExecutionStepState.DISPATCHED,
        },
    )
    assert await guard.list_unpublished_ids(tenant_id=42, space_ids=[8]) == set()

    await _set_upload_truth(
        visibility_engine,
        request_id=request_id,
        tenant_id=42,
        request_state=KnowledgeSpaceFileChangeExecutionState.APPLYING,
        file_status=KnowledgeFileStatus.SUCCESS.value,
        step_states=_all_steps(KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED),
    )
    assert await guard.list_unpublished_ids(tenant_id=42, space_ids=[8]) == {201, 202, file_id}

    await _set_upload_truth(
        visibility_engine,
        request_id=request_id,
        tenant_id=42,
        request_state=KnowledgeSpaceFileChangeExecutionState.APPLIED,
        file_status=KnowledgeFileStatus.SUCCESS.value,
        step_states=_all_steps(KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED),
    )
    assert await guard.list_unpublished_ids(tenant_id=42, space_ids=[8]) == set()


async def test_publication_guard_keeps_business_execution_failures_unpublished(visibility_engine):
    set_current_tenant_id(42)
    _request_id, file_id = await _seed_upload(
        visibility_engine,
        tenant_id=42,
        space_id=8,
        applicant_user_id=7,
        execution_state=KnowledgeSpaceFileChangeExecutionState.FAILED,
        file_status=KnowledgeFileStatus.FAILED.value,
        step_states=_all_steps(KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED),
    )
    guard = KnowledgeSpaceFilePublicationGuard(session_factory=_session_factory(visibility_engine))

    assert await guard.filter_published_ids(
        tenant_id=42,
        space_ids=[8],
        resource_ids=[file_id, 123456, file_id],
    ) == [123456]


async def test_failed_upload_folder_is_released_only_after_a_reusing_child_is_published(
    visibility_engine,
):
    set_current_tenant_id(42)
    failed_request_id, failed_file_id = await _seed_upload(
        visibility_engine,
        tenant_id=42,
        space_id=8,
        applicant_user_id=7,
        execution_state=KnowledgeSpaceFileChangeExecutionState.FAILED,
        file_status=KnowledgeFileStatus.FAILED.value,
        folder_ids=(201,),
    )
    parsing_request_id, parsing_file_id = await _seed_upload(
        visibility_engine,
        tenant_id=42,
        space_id=8,
        applicant_user_id=8,
        execution_state=KnowledgeSpaceFileChangeExecutionState.APPLYING,
        file_status=KnowledgeFileStatus.WAITING.value,
    )
    async with AsyncSession(bind=visibility_engine, expire_on_commit=False) as session:
        async with session.begin():
            parsing_file = (
                await session.exec(
                    select(KnowledgeFile).where(
                        KnowledgeFile.tenant_id == 42,
                        KnowledgeFile.id == parsing_file_id,
                    )
                )
            ).one()
            parsing_file.file_level_path = "/201"
            session.add(parsing_file)
    guard = KnowledgeSpaceFilePublicationGuard(session_factory=_session_factory(visibility_engine))

    # A second request that merely reuses the directory but is still parsing
    # must not expose the directory or either unpublished file.
    assert await guard.list_unpublished_ids(tenant_id=42, space_ids=[8]) == {
        201,
        failed_file_id,
        parsing_file_id,
    }

    await _set_upload_truth(
        visibility_engine,
        request_id=parsing_request_id,
        tenant_id=42,
        request_state=KnowledgeSpaceFileChangeExecutionState.APPLIED,
        file_status=KnowledgeFileStatus.SUCCESS.value,
        step_states=_all_steps(KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED),
    )

    # Approval order is irrelevant: once B is truly published, its ancestor
    # directory is shared formal structure and A may only keep A's file hidden.
    assert await guard.list_unpublished_ids(tenant_id=42, space_ids=[8]) == {failed_file_id}
    assert failed_request_id != parsing_request_id


class _StaticApproverResolver:
    user_ids = {8}
    failure: Exception | None = None

    @classmethod
    async def is_current_approver(cls, **kwargs) -> bool:
        del kwargs["tenant_id"], kwargs["space_id"]
        if cls.failure is not None:
            raise cls.failure
        return int(kwargs["user_id"]) in cls.user_ids


async def test_unpublished_preview_is_only_for_applicant_or_strict_current_approver(visibility_engine):
    set_current_tenant_id(42)
    _request_id, file_id = await _seed_upload(
        visibility_engine,
        tenant_id=42,
        space_id=8,
        applicant_user_id=7,
    )
    guard = KnowledgeSpaceFilePublicationGuard(
        session_factory=_session_factory(visibility_engine),
        approver_resolver=_StaticApproverResolver,
    )

    await guard.require_published_or_stakeholder(
        tenant_id=42,
        space_id=8,
        resource_id=file_id,
        viewer_user_id=7,
    )
    await guard.require_published_or_stakeholder(
        tenant_id=42,
        space_id=8,
        resource_id=file_id,
        viewer_user_id=8,
    )
    with pytest.raises(SpaceFileChangeRequestNotFoundError) as denied:
        await guard.require_published_or_stakeholder(
            tenant_id=42,
            space_id=8,
            resource_id=file_id,
            viewer_user_id=9,
        )
    assert "tenant-42.pdf" not in str(denied.value)


async def test_strict_approver_failure_fails_closed_for_unpublished_preview(visibility_engine):
    set_current_tenant_id(42)
    _request_id, file_id = await _seed_upload(
        visibility_engine,
        tenant_id=42,
        space_id=8,
        applicant_user_id=7,
    )
    _StaticApproverResolver.failure = SpaceFileChangeApproverUnavailableError()
    guard = KnowledgeSpaceFilePublicationGuard(
        session_factory=_session_factory(visibility_engine),
        approver_resolver=_StaticApproverResolver,
    )
    try:
        with pytest.raises(SpaceFileChangeApproverUnavailableError):
            await guard.require_published_or_stakeholder(
                tenant_id=42,
                space_id=8,
                resource_id=file_id,
                viewer_user_id=8,
            )
    finally:
        _StaticApproverResolver.failure = None


async def test_publication_guard_does_not_replace_existing_rebac_authorization(visibility_engine):
    set_current_tenant_id(42)
    request_id, file_id = await _seed_upload(
        visibility_engine,
        tenant_id=42,
        space_id=8,
        applicant_user_id=7,
    )
    await _set_upload_truth(
        visibility_engine,
        request_id=request_id,
        tenant_id=42,
        request_state=KnowledgeSpaceFileChangeExecutionState.APPLIED,
        file_status=KnowledgeFileStatus.SUCCESS.value,
        step_states=_all_steps(KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED),
    )
    guard = KnowledgeSpaceFilePublicationGuard(
        session_factory=_session_factory(visibility_engine),
        approver_resolver=_StaticApproverResolver,
    )

    # Passing the publication guard only means F046 does not hide this ID.
    # The caller must still perform its normal ReBAC authorization.
    await guard.require_published_or_stakeholder(
        tenant_id=42,
        space_id=8,
        resource_id=file_id,
        viewer_user_id=999,
    )


async def test_deletion_guard_activates_only_after_atomic_cutover_flag(visibility_engine):
    set_current_tenant_id(42)
    inactive_request_id = await _seed_delete(
        visibility_engine,
        tenant_id=42,
        space_id=8,
        resource_ids=(500, 501),
        execution_state=KnowledgeSpaceFileChangeExecutionState.APPLIED,
        cutover_active=False,
    )
    await _seed_delete(
        visibility_engine,
        tenant_id=42,
        space_id=9,
        resource_ids=(600,),
        execution_state=KnowledgeSpaceFileChangeExecutionState.APPLYING,
        cutover_active=True,
    )
    await _seed_delete(
        visibility_engine,
        tenant_id=99,
        space_id=8,
        resource_ids=(700,),
        execution_state=KnowledgeSpaceFileChangeExecutionState.APPLIED,
        cutover_active=True,
    )
    guard = KnowledgeSpaceDeletionGuard(session_factory=_session_factory(visibility_engine))

    # A committed delete remains guarded while request/F025 are still
    # APPLYING/DEFERRED and the authoritative purge has not finished.
    assert await guard.list_deleted_ids(tenant_id=42, space_ids=[8, 9]) == {600}

    async with AsyncSession(bind=visibility_engine, expire_on_commit=False) as session:
        async with session.begin():
            request = (
                await session.exec(
                    select(KnowledgeSpaceFileChangeRequest).where(
                        KnowledgeSpaceFileChangeRequest.tenant_id == 42,
                        KnowledgeSpaceFileChangeRequest.id == inactive_request_id,
                    )
                )
            ).one()
            request.execution_checkpoint = {DELETION_CUTOVER_ACTIVE_CHECKPOINT_KEY: True}
            session.add(request)

    assert await guard.list_deleted_ids(tenant_id=42, space_ids=[8, 9]) == {500, 501, 600}
    assert await guard.filter_not_deleted_ids(
        tenant_id=42,
        space_ids=[8, 9],
        resource_ids=[500, 800, 501, 800],
    ) == [800, 800]


async def test_mutation_projection_keeps_old_space_visible_and_hides_target_until_atomic_switch(
    visibility_engine,
):
    set_current_tenant_id(42)
    request_id = await _seed_mutation_fence(
        visibility_engine,
        tenant_id=42,
        source_space_id=8,
        target_space_id=9,
        resource_id=900,
    )
    await _seed_mutation_fence(
        visibility_engine,
        tenant_id=42,
        source_space_id=8,
        target_space_id=9,
        resource_id=901,
        fence_active=False,
    )
    await _seed_mutation_fence(
        visibility_engine,
        tenant_id=99,
        source_space_id=8,
        target_space_id=9,
        resource_id=999,
    )
    projection = MutationReadProjectionService(
        session_factory=_session_factory(visibility_engine),
    )

    assert await projection.list_invisible_ids(tenant_id=42, space_ids=[8]) == set()
    assert await projection.list_invisible_ids(tenant_id=42, space_ids=[9]) == {900}
    await projection.require_current_view(tenant_id=42, space_id=8, resource_id=900)
    with pytest.raises(SpaceFileChangeRequestNotFoundError):
        await projection.require_current_view(tenant_id=42, space_id=9, resource_id=900)

    async with AsyncSession(bind=visibility_engine, expire_on_commit=False) as session:
        async with session.begin():
            request = (
                await session.exec(
                    select(KnowledgeSpaceFileChangeRequest).where(
                        KnowledgeSpaceFileChangeRequest.tenant_id == 42,
                        KnowledgeSpaceFileChangeRequest.id == request_id,
                    )
                )
            ).one()
            request.execution_state = KnowledgeSpaceFileChangeExecutionState.APPLIED
            request.execution_checkpoint = {
                **request.execution_checkpoint,
                MUTATION_TRANSITION_PHASE_CHECKPOINT_KEY: "new_view",
            }
            session.add(request)

    assert await projection.list_invisible_ids(tenant_id=42, space_ids=[8]) == {900}
    assert await projection.list_invisible_ids(tenant_id=42, space_ids=[9]) == set()
    await projection.require_current_view(tenant_id=42, space_id=9, resource_id=900)
    with pytest.raises(SpaceFileChangeRequestNotFoundError):
        await projection.require_current_view(tenant_id=42, space_id=8, resource_id=900)


async def test_rename_query_uses_old_production_before_switch_and_expands_new_name_after_cleanup_crash(
    visibility_engine,
):
    set_current_tenant_id(42)
    request_id = await _seed_rename_projection(
        visibility_engine,
        tenant_id=42,
        space_id=8,
        resource_id=910,
        phase="old_view",
    )
    projection = MutationReadProjectionService(session_factory=_session_factory(visibility_engine))
    old_production_rows = ["document_name: old.pdf\nbody"]

    def fake_filename_retrieval(query: str) -> list[str]:
        terms = query.replace("\n", " ").split()
        return [row for row in old_production_rows if any(term in row for term in terms)]

    old_view_query = await projection.expand_retrieval_query(
        tenant_id=42,
        space_id=8,
        query="find new.pdf",
    )
    assert old_view_query == "find new.pdf"
    assert fake_filename_retrieval(old_view_query) == []

    async with AsyncSession(bind=visibility_engine, expire_on_commit=False) as session:
        async with session.begin():
            request = await session.get(KnowledgeSpaceFileChangeRequest, request_id)
            request.execution_state = KnowledgeSpaceFileChangeExecutionState.APPLIED
            request.execution_checkpoint = {
                **request.execution_checkpoint,
                MUTATION_TRANSITION_PHASE_CHECKPOINT_KEY: "new_view",
            }
            session.add(request)

    new_view_query = await projection.expand_retrieval_query(
        tenant_id=42,
        space_id=8,
        query="find new.pdf",
    )
    assert new_view_query == "find new.pdf\nfind old.pdf"
    assert fake_filename_retrieval(new_view_query) == old_production_rows


async def test_visibility_guards_batch_across_spaces_without_per_resource_queries(visibility_engine):
    set_current_tenant_id(42)
    _request_one, file_one = await _seed_upload(
        visibility_engine,
        tenant_id=42,
        space_id=8,
        applicant_user_id=7,
        folder_ids=(201,),
    )
    _request_two, file_two = await _seed_upload(
        visibility_engine,
        tenant_id=42,
        space_id=9,
        applicant_user_id=7,
        folder_ids=(301,),
    )
    await _seed_delete(
        visibility_engine,
        tenant_id=42,
        space_id=9,
        resource_ids=(401, 402),
        execution_state=KnowledgeSpaceFileChangeExecutionState.APPLIED,
        cutover_active=True,
    )
    publication_guard = KnowledgeSpaceFilePublicationGuard(session_factory=_session_factory(visibility_engine))
    deletion_guard = KnowledgeSpaceDeletionGuard(session_factory=_session_factory(visibility_engine))

    statements: list[str] = []

    def record_statement(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(visibility_engine.sync_engine, "before_cursor_execute", record_statement)
    try:
        assert await publication_guard.list_unpublished_ids(tenant_id=42, space_ids=[8, 9]) == {
            201,
            file_one,
            301,
            file_two,
        }
        assert len(statements) == 2
        statements.clear()
        assert await deletion_guard.list_deleted_ids(tenant_id=42, space_ids=[8, 9]) == {401, 402}
        # Active footprint is the post-cutover residue truth, so guard reads
        # request checkpoint + relational footprint in one bounded join and
        # never scans all historical APPLIED delete requests.
        assert len(statements) == 1
    finally:
        event.remove(visibility_engine.sync_engine, "before_cursor_execute", record_statement)
