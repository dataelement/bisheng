from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import set_current_tenant_id
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile, KnowledgeFileStatus
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
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_execution_step_repository import (
    KnowledgeSpaceFileChangeExecutionStepRepository,
)
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_footprint_repository import (
    KnowledgeSpaceFileChangeFootprintRepository,
)
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_request_repository import (
    KnowledgeSpaceFileChangeRequestRepository,
)
from bisheng.knowledge.domain.services.knowledge_space_deletion_guard import KnowledgeSpaceDeletionGuard
from bisheng.knowledge.domain.services.knowledge_space_file_change_execution_coordinator import (
    KnowledgeSpaceFileChangeExecutionCoordinator,
)
from bisheng.knowledge.domain.services.knowledge_space_mutation_executor import (
    DeleteExecutionStepCode,
    KnowledgeSpaceMutationExecutor,
    MutationStepContext,
    VerifiedMutationStepResult,
)


@pytest.fixture
async def delete_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(
            SQLModel.metadata.create_all,
            tables=[
                Knowledge.__table__,
                KnowledgeFile.__table__,
                KnowledgeDocument.__table__,
                KnowledgeDocumentVersion.__table__,
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


async def _seed_delete(
    engine: AsyncEngine,
    *,
    folder: bool = False,
    shared_parent: bool = False,
) -> tuple[int, int, int, int]:
    async with AsyncSession(bind=engine, expire_on_commit=False) as session:
        async with session.begin():
            space = Knowledge(tenant_id=42, name="space", type=KnowledgeTypeEnum.SPACE.value)
            session.add(space)
            await session.flush()
            parent = KnowledgeFile(
                tenant_id=42,
                knowledge_id=int(space.id),
                user_id=7,
                file_name="shared",
                file_type=FileType.DIR.value,
                file_level_path="",
                level=0,
                status=KnowledgeFileStatus.SUCCESS.value,
            )
            session.add(parent)
            await session.flush()
            root = KnowledgeFile(
                tenant_id=42,
                knowledge_id=int(space.id),
                user_id=7,
                file_name="target" if folder else "target.pdf",
                file_type=FileType.DIR.value if folder else FileType.FILE.value,
                file_level_path=f"/{parent.id}",
                level=1,
                object_name=None if folder else "tenant/42/target.pdf",
                preview_file_object_name=None if folder else "tenant/42/target-preview.pdf",
                status=KnowledgeFileStatus.SUCCESS.value,
            )
            session.add(root)
            await session.flush()
            if not folder:
                document = KnowledgeDocument(
                    knowledge_id=int(space.id),
                    file_level_path=f"/{parent.id}",
                    level=1,
                )
                session.add(document)
                await session.flush()
                version = KnowledgeDocumentVersion(
                    document_id=int(document.id),
                    knowledge_file_id=int(root.id),
                    version_no=1,
                    is_primary=True,
                )
                session.add(version)
                await session.flush()
                document.primary_version_id = int(version.id)
                session.add(document)
            if folder:
                child = KnowledgeFile(
                    tenant_id=42,
                    knowledge_id=int(space.id),
                    user_id=7,
                    file_name="child.pdf",
                    file_type=FileType.FILE.value,
                    file_level_path=f"/{parent.id}/{root.id}",
                    level=2,
                    object_name="tenant/42/child.pdf",
                    status=KnowledgeFileStatus.SUCCESS.value,
                )
                session.add(child)
            if shared_parent:
                session.add(
                    KnowledgeFile(
                        tenant_id=42,
                        knowledge_id=int(space.id),
                        user_id=7,
                        file_name="keep.pdf",
                        file_type=FileType.FILE.value,
                        file_level_path=f"/{parent.id}",
                        level=1,
                        object_name="tenant/42/keep.pdf",
                        status=KnowledgeFileStatus.SUCCESS.value,
                    )
                )
            request = KnowledgeSpaceFileChangeRequest(
                tenant_id=42,
                space_id=int(space.id),
                action=KnowledgeSpaceFileChangeAction.DELETE,
                resource_type=(
                    KnowledgeSpaceFileChangeResourceType.FOLDER
                    if folder
                    else KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE
                ),
                resource_id=int(root.id),
                applicant_user_id=7,
                business_key="knowledge-space-change:delete-cutover",
                request_fingerprint="delete-cutover-fingerprint",
                approval_instance_id=501,
                file_name=root.file_name,
                source_parent_id=int(parent.id),
                action_snapshot={
                    "old_name": root.file_name,
                    "old_path": root.file_level_path,
                    "old_level": root.level,
                },
            )
            session.add(request)
            await session.flush()
            session.add(
                KnowledgeSpaceFileChangeFootprint(
                    tenant_id=42,
                    request_id=int(request.id),
                    space_id=int(space.id),
                    resource_type=request.resource_type,
                    resource_id=int(root.id),
                    path_root=f"/{parent.id}/{root.id}/" if folder else f"/{parent.id}/",
                    lock_scope=(
                        KnowledgeSpaceFileChangeLockScope.SUBTREE if folder else KnowledgeSpaceFileChangeLockScope.EXACT
                    ),
                )
            )
    return int(space.id), int(parent.id), int(root.id), int(request.id)


async def _get_request(engine: AsyncEngine, request_id: int):
    async with AsyncSession(bind=engine, expire_on_commit=False) as session:
        return (
            await session.exec(
                select(KnowledgeSpaceFileChangeRequest).where(KnowledgeSpaceFileChangeRequest.id == request_id)
            )
        ).one()


async def test_delete_prepare_is_durable_and_zero_destructive(delete_engine):
    set_current_tenant_id(42)
    _, parent_id, root_id, request_id = await _seed_delete(delete_engine, folder=True)
    executor = KnowledgeSpaceMutationExecutor(
        session_factory=_session_factory(delete_engine),
        execution_token_factory=lambda: "delete-token",
        mutation_execution_validator=lambda **_kwargs: None,
    )

    result = await executor.execute(
        request_id=request_id,
    )

    assert result.execution_token == "delete-token"
    async with AsyncSession(bind=delete_engine) as session:
        rows = list((await session.exec(select(KnowledgeFile).order_by(KnowledgeFile.id))).all())
        assert {int(row.id) for row in rows} >= {parent_id, root_id}
        request = await session.get(KnowledgeSpaceFileChangeRequest, request_id)
        assert request.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLYING
        assert request.execution_checkpoint["delete_manifest"]["root"]["id"] == root_id
        steps = list(
            (
                await session.exec(
                    select(KnowledgeSpaceFileChangeExecutionStep).where(
                        KnowledgeSpaceFileChangeExecutionStep.request_id == request_id
                    )
                )
            ).all()
        )
        assert {step.step_code for step in steps} == set(DeleteExecutionStepCode.ALL)
        assert next(step for step in steps if step.step_code == DeleteExecutionStepCode.PREPARE).state == (
            KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED
        )
        assert all(step.idempotency_key == f"f046:{request_id}:{step.step_code}" for step in steps)


async def test_delete_cutover_atomically_deletes_db_and_activates_guard(delete_engine):
    set_current_tenant_id(42)
    space_id, parent_id, root_id, request_id = await _seed_delete(delete_engine)
    executor = KnowledgeSpaceMutationExecutor(
        session_factory=_session_factory(delete_engine),
        execution_token_factory=lambda: "delete-token",
        mutation_execution_validator=lambda **_kwargs: None,
    )
    request = await _get_request(delete_engine, request_id)
    await executor.execute(
        request_id=request_id,
    )

    assert await executor.cutover_delete(
        request_id=request_id,
        execution_token="delete-token",
    )

    async with AsyncSession(bind=delete_engine) as session:
        assert await session.get(KnowledgeFile, root_id) is None
        assert await session.get(KnowledgeFile, parent_id) is not None
        assert (await session.exec(select(KnowledgeDocumentVersion))).all() == []
        assert (await session.exec(select(KnowledgeDocument))).all() == []
        request = await session.get(KnowledgeSpaceFileChangeRequest, request_id)
        assert request.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLYING
        assert request.execution_checkpoint["delete_phase"] == "purging"
        purge_steps = list(
            (
                await session.exec(
                    select(KnowledgeSpaceFileChangeExecutionStep).where(
                        KnowledgeSpaceFileChangeExecutionStep.step_code.in_(DeleteExecutionStepCode.PURGE)
                    )
                )
            ).all()
        )
        assert all(step.state == KnowledgeSpaceFileChangeExecutionStepState.PENDING for step in purge_steps)

    guard = KnowledgeSpaceDeletionGuard(session_factory=_session_factory(delete_engine))
    assert await guard.list_deleted_ids(tenant_id=42, space_ids=[space_id]) == {root_id}


async def test_delete_cutover_revalidates_permission_after_prepare_and_rolls_back_on_revoke(delete_engine):
    set_current_tenant_id(42)
    _, _, root_id, request_id = await _seed_delete(delete_engine)
    validation_calls = 0

    async def revoked_after_prepare(**_kwargs):
        nonlocal validation_calls
        validation_calls += 1
        if validation_calls == 2:
            raise PermissionError("delete permission revoked")

    executor = KnowledgeSpaceMutationExecutor(
        session_factory=_session_factory(delete_engine),
        execution_token_factory=lambda: "delete-token",
        mutation_execution_validator=revoked_after_prepare,
    )
    request = await _get_request(delete_engine, request_id)
    await executor.execute(
        request_id=request_id,
    )

    with pytest.raises(PermissionError, match="revoked"):
        await executor.cutover_delete(
            request_id=request_id,
            execution_token="delete-token",
        )

    assert validation_calls == 2
    async with AsyncSession(bind=delete_engine) as session:
        assert await session.get(KnowledgeFile, root_id) is not None
        request = await session.get(KnowledgeSpaceFileChangeRequest, request_id)
        assert request.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLYING


async def test_delete_finalization_keeps_guard_until_all_purge_verified(delete_engine):
    set_current_tenant_id(42)
    _, _, _, request_id = await _seed_delete(delete_engine)
    executor = KnowledgeSpaceMutationExecutor(
        session_factory=_session_factory(delete_engine),
        execution_token_factory=lambda: "delete-token",
        mutation_execution_validator=lambda **_kwargs: None,
    )
    await executor.execute(
        request_id=request_id,
    )
    await executor.cutover_delete(
        request_id=request_id,
        execution_token="delete-token",
    )

    with pytest.raises(RuntimeError, match="every verified current-generation step"):
        await executor.finalize_delete_execution(
            request_id=request_id,
            execution_token="delete-token",
        )

    async with AsyncSession(bind=delete_engine) as session:
        current = await session.get(KnowledgeSpaceFileChangeRequest, request_id)
        footprints = list(
            (
                await session.exec(
                    select(KnowledgeSpaceFileChangeFootprint).where(
                        KnowledgeSpaceFileChangeFootprint.request_id == request_id
                    )
                )
            ).all()
        )
        assert current.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLYING
        assert current.execution_checkpoint["deletion_cutover_active"] is True
        assert len(footprints) == 1


async def test_delete_finalization_locks_request_footprint_then_steps(
    delete_engine,
    monkeypatch: pytest.MonkeyPatch,
):
    set_current_tenant_id(42)
    _, _, _, request_id = await _seed_delete(delete_engine)
    executor = KnowledgeSpaceMutationExecutor(
        session_factory=_session_factory(delete_engine),
        execution_token_factory=lambda: "delete-token",
        mutation_execution_validator=lambda **_kwargs: None,
    )
    await executor.execute(
        request_id=request_id,
    )
    await executor.cutover_delete(
        request_id=request_id,
        execution_token="delete-token",
    )
    async with AsyncSession(bind=delete_engine, expire_on_commit=False) as session:
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
            for row in rows:
                row.state = KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED
                row.attempt_token = "delete-token"
                session.add(row)

    order: list[str] = []
    original_get = KnowledgeSpaceFileChangeRequestRepository.get_by_id
    original_retire = KnowledgeSpaceFileChangeFootprintRepository.retire_delete_guard
    original_list = KnowledgeSpaceFileChangeExecutionStepRepository.list_by_request

    async def record_get(repository, **kwargs):
        if kwargs.get("for_update"):
            order.append("request")
        return await original_get(repository, **kwargs)

    async def record_retire(repository, **kwargs):
        order.append("footprint")
        return await original_retire(repository, **kwargs)

    async def record_list(repository, **kwargs):
        if kwargs.get("for_update"):
            order.append("steps")
        return await original_list(repository, **kwargs)

    monkeypatch.setattr(KnowledgeSpaceFileChangeRequestRepository, "get_by_id", record_get)
    monkeypatch.setattr(KnowledgeSpaceFileChangeFootprintRepository, "retire_delete_guard", record_retire)
    monkeypatch.setattr(KnowledgeSpaceFileChangeExecutionStepRepository, "list_by_request", record_list)

    assert await executor.finalize_delete_execution(
        request_id=request_id,
        execution_token="delete-token",
    )
    assert order == ["request", "footprint", "steps"]


def _delete_purge_context(step_code: str, *, manifest: dict | None = None) -> MutationStepContext:
    return MutationStepContext(
        tenant_id=42,
        request_id=301,
        execution_token="delete-token",
        action=KnowledgeSpaceFileChangeAction.DELETE,
        step_code=step_code,
        idempotency_key=f"f046:301:{step_code}",
        resource_type=KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE,
        resource_id=101,
        applicant_user_id=7,
        source_space_id=10,
        target_space_id=None,
        manifest=manifest or {"file_ids": [101]},
    )


async def test_delete_fga_purge_requires_strict_authoritative_read_after(monkeypatch: pytest.MonkeyPatch):
    strict_delete = AsyncMock(side_effect=RuntimeError("tuple residue"))
    monkeypatch.setattr(
        "bisheng.permission.domain.services.owner_service.OwnerService.delete_resource_tuples_strict",
        strict_delete,
    )
    context = _delete_purge_context(
        DeleteExecutionStepCode.FGA,
        manifest={
            "file_ids": [101],
            "fga_resources": [{"resource_type": "knowledge_file", "resource_id": "101"}],
        },
    )

    with pytest.raises(RuntimeError, match="tuple residue"):
        await KnowledgeSpaceMutationExecutor._apply_delete_purge_step(context)
    strict_delete.assert_awaited_once_with("knowledge_file", "101")


async def test_delete_minio_purge_fails_when_object_exists_after_remove(monkeypatch: pytest.MonkeyPatch):
    storage = SimpleNamespace(
        bucket="bisheng",
        remove_object=AsyncMock(),
        object_exists=AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "bisheng.core.storage.minio.minio_manager.get_minio_storage",
        AsyncMock(return_value=storage),
    )
    context = _delete_purge_context(
        DeleteExecutionStepCode.MINIO,
        manifest={"file_ids": [101], "object_names": ["tenant/42/101.pdf"]},
    )

    with pytest.raises(RuntimeError, match="MinIO purge verification found object residue"):
        await KnowledgeSpaceMutationExecutor._apply_delete_purge_step(context)
    storage.remove_object.assert_awaited_once_with(bucket_name="bisheng", object_name="tenant/42/101.pdf")
    storage.object_exists.assert_awaited_once_with(bucket_name="bisheng", object_name="tenant/42/101.pdf")


async def test_delete_es_purge_fails_when_file_scoped_count_finds_residue(monkeypatch: pytest.MonkeyPatch):
    indices = SimpleNamespace(exists=lambda **_kwargs: True, refresh=lambda **_kwargs: None)
    client = SimpleNamespace(
        indices=indices,
        delete_by_query=lambda **_kwargs: {"deleted": 1, "failures": []},
        count=lambda **kwargs: (
            {"count": 1} if kwargs["body"]["query"]["terms"]["metadata.document_id"] == [101] else {"count": 0}
        ),
    )
    es_store = SimpleNamespace(client=client)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge.KnowledgeDao.query_by_id",
        lambda _space_id: SimpleNamespace(index_name="space-index"),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.knowledge_rag.KnowledgeRag.init_knowledge_es_vectorstore_sync",
        lambda **_kwargs: es_store,
    )

    with pytest.raises(RuntimeError, match="Elasticsearch purge verification found file residue"):
        await KnowledgeSpaceMutationExecutor._apply_delete_purge_step(_delete_purge_context(DeleteExecutionStepCode.ES))


async def test_delete_milvus_purge_fails_when_file_scoped_count_finds_residue(monkeypatch: pytest.MonkeyPatch):
    collection = SimpleNamespace(
        delete=lambda **_kwargs: None,
        flush=lambda: None,
        query=lambda **kwargs: [{"count(*)": 1}] if kwargs["expr"] == "document_id in [101]" else [{"count(*)": 0}],
    )
    vector_store = SimpleNamespace(col=collection)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge.KnowledgeDao.query_by_id",
        lambda _space_id: SimpleNamespace(collection_name="space-collection"),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.knowledge_rag.KnowledgeRag.init_knowledge_milvus_vectorstore_sync",
        lambda *_args, **_kwargs: vector_store,
    )

    with pytest.raises(RuntimeError, match="Milvus purge verification found file residue"):
        await KnowledgeSpaceMutationExecutor._apply_delete_purge_step(
            _delete_purge_context(DeleteExecutionStepCode.MILVUS)
        )


async def test_delete_purge_retries_without_resurrection_and_retires_guard_footprint(delete_engine):
    set_current_tenant_id(42)
    space_id, _, root_id, request_id = await _seed_delete(delete_engine)
    attempts: list[str] = []

    async def purge_effect(context):
        attempts.append(context.step_code)
        if context.step_code == DeleteExecutionStepCode.MINIO and attempts.count(context.step_code) == 1:
            raise RuntimeError("minio unavailable")
        return VerifiedMutationStepResult(result_digest=f"purged:{context.step_code}")

    executor = KnowledgeSpaceMutationExecutor(
        session_factory=_session_factory(delete_engine),
        execution_token_factory=lambda: "delete-token",
        delete_purge_applier=purge_effect,
        mutation_execution_validator=lambda **_kwargs: None,
    )
    await executor.execute(
        request_id=request_id,
    )
    await executor.cutover_delete(
        request_id=request_id,
        execution_token="delete-token",
    )
    guard = KnowledgeSpaceDeletionGuard(session_factory=_session_factory(delete_engine))

    with pytest.raises(RuntimeError, match="minio unavailable"):
        await executor.purge_delete(request_id=request_id, execution_token="delete-token")
    assert await guard.list_deleted_ids(tenant_id=42, space_ids=[space_id]) == {root_id}
    async with AsyncSession(bind=delete_engine) as session:
        assert await session.get(KnowledgeFile, root_id) is None
        failed_request = await session.get(KnowledgeSpaceFileChangeRequest, request_id)
        assert failed_request.execution_state == KnowledgeSpaceFileChangeExecutionState.FAILED
        assert failed_request.execution_checkpoint["delete_phase"] == "purge_failed"

    coordinator = KnowledgeSpaceFileChangeExecutionCoordinator(
        session_factory=_session_factory(delete_engine),
        execution_token_factory=lambda: "delete-retry-token",
    )
    queued = await coordinator.queue_retry(tenant_id=42, request_id=request_id)
    _, retried_steps = await coordinator._load_current(identity=queued)
    assert {step.attempt_token for step in retried_steps} == {"delete-retry-token"}
    assert next(step for step in retried_steps if step.step_code == DeleteExecutionStepCode.DB_CUTOVER).state == (
        KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED
    )
    assert next(step for step in retried_steps if step.step_code == DeleteExecutionStepCode.MINIO).state == (
        KnowledgeSpaceFileChangeExecutionStepState.PENDING
    )
    identity = await coordinator.begin_execution(tenant_id=42, request_id=request_id)
    assert queued.execution_token == identity.execution_token == "delete-retry-token"

    assert await executor.purge_delete(request_id=request_id, execution_token=identity.execution_token)
    assert await guard.list_deleted_ids(tenant_id=42, space_ids=[space_id]) == set()
    async with AsyncSession(bind=delete_engine) as session:
        footprints = list(
            (
                await session.exec(
                    select(KnowledgeSpaceFileChangeFootprint).where(
                        KnowledgeSpaceFileChangeFootprint.request_id == request_id
                    )
                )
            ).all()
        )
        assert footprints == []
        assert await session.get(KnowledgeFile, root_id) is None
        applied_request = await session.get(KnowledgeSpaceFileChangeRequest, request_id)
        assert applied_request.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLIED
        assert applied_request.execution_checkpoint["delete_phase"] == "completed"
    assert attempts.count(DeleteExecutionStepCode.FGA) == 1


async def test_delete_purge_rejects_enqueue_receipt_as_completion(delete_engine):
    set_current_tenant_id(42)
    space_id, _, root_id, request_id = await _seed_delete(delete_engine)

    async def task_id_only(_context):
        return "celery-task-id"

    executor = KnowledgeSpaceMutationExecutor(
        session_factory=_session_factory(delete_engine),
        execution_token_factory=lambda: "delete-token",
        delete_purge_applier=task_id_only,
        mutation_execution_validator=lambda **_kwargs: None,
    )
    await executor.execute(
        request_id=request_id,
    )
    await executor.cutover_delete(
        request_id=request_id,
        execution_token="delete-token",
    )

    with pytest.raises(TypeError, match="verified mutation step result"):
        await executor.purge_delete(request_id=request_id, execution_token="delete-token")
    guard = KnowledgeSpaceDeletionGuard(session_factory=_session_factory(delete_engine))
    assert await guard.list_deleted_ids(tenant_id=42, space_ids=[space_id]) == {root_id}


async def test_delete_never_prunes_shared_parent_with_published_child(delete_engine):
    set_current_tenant_id(42)
    _, parent_id, _, request_id = await _seed_delete(delete_engine, shared_parent=True)
    executor = KnowledgeSpaceMutationExecutor(
        session_factory=_session_factory(delete_engine),
        execution_token_factory=lambda: "delete-token",
        mutation_execution_validator=lambda **_kwargs: None,
    )
    await executor.execute(
        request_id=request_id,
    )
    await executor.cutover_delete(
        request_id=request_id,
        execution_token="delete-token",
    )

    async with AsyncSession(bind=delete_engine) as session:
        assert await session.get(KnowledgeFile, parent_id) is not None
        surviving_children = list(
            (await session.exec(select(KnowledgeFile).where(KnowledgeFile.file_level_path == f"/{parent_id}"))).all()
        )
        assert [row.file_name for row in surviving_children] == ["keep.pdf"]
