"""Direct deletion commits its DB graph and recoverable cleanup together."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge_space import SpaceFileChangeConflictError
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_file_change_execution_step import (
    KnowledgeSpaceFileChangeExecutionStep,
)
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeFootprint,
    KnowledgeSpaceFileChangeRequest,
)
from bisheng.knowledge.domain.models.knowledge_space_upload_stage import KnowledgeSpaceUploadStage
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_compensation_repository import (
    KnowledgeSpaceFileChangeCompensationRepository,
)
from bisheng.knowledge.domain.repositories.knowledge_space_mutation_repository import KnowledgeSpaceMutationRepository
from bisheng.knowledge.domain.services.knowledge_permission_service import KnowledgeFilePermissionRecord
from bisheng.knowledge.domain.services.knowledge_space_deletion_guard import KnowledgeSpaceDeletionGuard
from bisheng.knowledge.domain.services.knowledge_space_direct_delete_service import KnowledgeSpaceDirectDeleteService
from bisheng.knowledge.domain.services.knowledge_space_mutation_executor import (
    DeleteExecutionStepCode,
    KnowledgeSpaceMutationExecutor,
    MutationStepContext,
    VerifiedMutationStepResult,
)


@pytest.fixture
async def direct_delete_db():
    token = set_current_tenant_id(42)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(
            SQLModel.metadata.create_all,
            tables=[
                model.__table__
                for model in (
                    Knowledge,
                    KnowledgeFile,
                    KnowledgeDocument,
                    KnowledgeDocumentVersion,
                    KnowledgeSpaceFileChangeRequest,
                    KnowledgeSpaceFileChangeFootprint,
                    KnowledgeSpaceFileChangeExecutionStep,
                    KnowledgeSpaceUploadStage,
                )
            ],
        )

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    async with sessions() as session, session.begin():
        space = Knowledge(tenant_id=42, name="space", type=KnowledgeTypeEnum.SPACE.value)
        session.add(space)
        await session.flush()
        parent = KnowledgeFile(
            tenant_id=42,
            knowledge_id=space.id,
            user_id=5,
            file_name="keep",
            file_type=0,
            file_level_path="",
            level=0,
            status=2,
        )
        session.add(parent)
        await session.flush()
        root = KnowledgeFile(
            tenant_id=42,
            knowledge_id=space.id,
            user_id=5,
            file_name="delete",
            file_type=0,
            file_level_path=f"/{parent.id}",
            level=1,
            status=2,
        )
        session.add(root)
        await session.flush()
        child = KnowledgeFile(
            tenant_id=42,
            knowledge_id=space.id,
            user_id=5,
            file_name="child.pdf",
            file_type=1,
            file_level_path=f"/{parent.id}/{root.id}",
            level=2,
            status=2,
            object_name="original/child",
        )
        session.add(child)
        await session.flush()
        document = KnowledgeDocument(knowledge_id=space.id, file_level_path=child.file_level_path, level=2)
        session.add(document)
        await session.flush()
        version = KnowledgeDocumentVersion(
            document_id=document.id, knowledge_file_id=child.id, version_no=1, is_primary=True
        )
        session.add(version)
        await session.flush()
        document.primary_version_id = version.id
        session.add(document)
    try:
        yield SimpleNamespace(sessions=sessions, root=root, child=child, parent=parent, space=space)
    finally:
        await engine.dispose()
        current_tenant_id.reset(token)


def _service(db, **overrides):
    async def records(resources):
        return [
            KnowledgeFilePermissionRecord(
                tenant_id=42,
                resource_type=kind,
                resource_id=str(resource_id),
                status="ACTIVE" if kind == "folder" else "SUCCESS",
                owner_user_id=5,
                permission_version=1,
                context_version="snapshot",
                mode="INHERIT",
                parent_type="folder",
                parent_id=str(db.parent.id if resource_id == db.root.id else db.root.id),
            )
            for kind, resource_id in resources
        ]

    return KnowledgeSpaceDirectDeleteService(
        authorize=overrides.pop("authorize", AsyncMock()),
        load_permission_records=records,
        session_factory=db.sessions,
        **overrides,
    )


async def _requests(db):
    async with db.sessions() as session:
        return list((await session.exec(select(KnowledgeSpaceFileChangeRequest))).all())


async def test_db_failure_rolls_back_rows_documents_and_cleanup_ledger(direct_delete_db):
    db = direct_delete_db

    class FailingRepository(KnowledgeSpaceMutationRepository):
        async def apply_delete_cutover(self, **kwargs):
            await super().apply_delete_cutover(**kwargs)
            raise RuntimeError("simulated DM8 delete/commit failure")

    dispatch = AsyncMock()
    service = _service(db, repository_factory=FailingRepository, dispatch_purge=dispatch)
    with pytest.raises(RuntimeError, match="simulated DM8"):
        await service.delete(resource=db.root, applicant_user_id=5)
    async with db.sessions() as session:
        assert await session.get(KnowledgeFile, db.root.id)
        assert await session.get(KnowledgeFile, db.child.id)
        assert (await session.exec(select(KnowledgeDocumentVersion))).all()
        assert (await session.exec(select(KnowledgeDocument))).all()
        assert (await session.exec(select(KnowledgeSpaceFileChangeFootprint))).all() == []
        assert (await session.exec(select(KnowledgeSpaceFileChangeExecutionStep))).all() == []
    assert await _requests(db) == []
    dispatch.assert_not_awaited()


async def test_cutover_and_cleanup_intent_commit_before_dispatch(direct_delete_db):
    db = direct_delete_db

    async def dispatch(**kwargs):
        async with db.sessions() as session:
            assert await session.get(KnowledgeFile, db.root.id) is None
            assert await session.get(KnowledgeFile, db.child.id) is None
            assert await session.get(KnowledgeFile, db.parent.id)
            assert (await session.exec(select(KnowledgeDocumentVersion))).all() == []
            assert (await session.exec(select(KnowledgeDocument))).all() == []
            request = await session.get(KnowledgeSpaceFileChangeRequest, kwargs["request_id"])
            assert request.execution_token == kwargs["execution_token"]
            assert request.execution_checkpoint["direct_delete"] is True
            assert request.approval_instance_id is None

    service = _service(db, dispatch_purge=AsyncMock(side_effect=dispatch))
    manifest = await service.delete(resource=db.root, applicant_user_id=5)
    assert set(manifest["file_ids"]) == {db.child.id}
    (request,) = await _requests(db)
    assert len(request.execution_checkpoint["delete_manifest"]["fga_permission_records"]) == 2
    async with db.sessions() as session:
        steps = (await session.exec(select(KnowledgeSpaceFileChangeExecutionStep))).all()
        assert {row.step_code for row in steps if row.state == "succeeded"} == {
            DeleteExecutionStepCode.PREPARE,
            DeleteExecutionStepCode.DB_CUTOVER,
        }
    guard = KnowledgeSpaceDeletionGuard(session_factory=db.sessions)
    assert await guard.list_deleted_ids(tenant_id=42, space_ids=[db.space.id]) == {db.root.id, db.child.id}


async def test_broker_failure_remains_discoverable_without_business_rows(direct_delete_db):
    db = direct_delete_db
    service = _service(db, dispatch_purge=AsyncMock(side_effect=ConnectionError("broker offline")))
    await service.delete(resource=db.root, applicant_user_id=5)
    (request,) = await _requests(db)
    async with db.sessions() as session:
        candidates, _, _ = await KnowledgeSpaceFileChangeCompensationRepository(session).list_cleanup_candidates(
            tenant_id=42,
            after_request_id=0,
            now=datetime.now(UTC).replace(tzinfo=None),
            limit=20,
        )
    assert [(row.request_id, row.kind) for row in candidates] == [(request.id, "delete_purge")]


async def test_expanded_child_authorization_failure_has_no_destructive_effect(direct_delete_db):
    db = direct_delete_db
    authorize = AsyncMock(side_effect=[None, PermissionError("child delete denied")])
    dispatch = AsyncMock()
    with pytest.raises(PermissionError):
        await _service(db, authorize=authorize, dispatch_purge=dispatch).delete(resource=db.root, applicant_user_id=5)
    assert await _requests(db) == []
    dispatch.assert_not_awaited()
    async with db.sessions() as session:
        assert await session.get(KnowledgeFile, db.root.id)


async def test_direct_purge_failure_retries_same_snapshot_and_finishes(direct_delete_db):
    db = direct_delete_db
    await _service(db, dispatch_purge=AsyncMock()).delete(resource=db.root, applicant_user_id=5)
    (request,) = await _requests(db)
    applied = []
    fail = True

    async def purge(context):
        nonlocal fail
        assert context.manifest["fga_permission_records"]
        applied.append(context.step_code)
        if context.step_code == DeleteExecutionStepCode.MINIO and fail:
            fail = False
            raise ConnectionError("MinIO offline")
        return VerifiedMutationStepResult(result_digest=f"verified:{context.step_code}")

    executor = KnowledgeSpaceMutationExecutor(session_factory=db.sessions, delete_purge_applier=purge)
    prepared = await executor.prepare_execution(request_id=request.id)
    assert prepared.execution_token == request.execution_token
    with pytest.raises(ConnectionError):
        await executor.purge_delete(request_id=request.id, execution_token=request.execution_token)
    (failed,) = await _requests(db)
    assert failed.execution_state == "applying"
    assert failed.execution_checkpoint["delete_phase"] == "purging"
    assert await executor.purge_delete(request_id=request.id, execution_token=request.execution_token)
    (completed,) = await _requests(db)
    assert completed.execution_state == "applied"
    assert applied.count(DeleteExecutionStepCode.FGA) == 1
    completed_effects = list(applied)
    assert await executor.purge_delete(request_id=request.id, execution_token=request.execution_token)
    assert applied == completed_effects
    assert (
        await KnowledgeSpaceDeletionGuard(session_factory=db.sessions).list_deleted_ids(
            tenant_id=42,
            space_ids=[db.space.id],
        )
        == set()
    )


async def test_foreign_tenant_delete_is_rejected_before_read_or_dispatch(direct_delete_db):
    db = direct_delete_db
    token = set_current_tenant_id(99)
    dispatch = AsyncMock()
    try:
        with pytest.raises(RuntimeError, match="tenant context"):
            await _service(db, dispatch_purge=dispatch).delete(resource=db.root, applicant_user_id=5)
        dispatch.assert_not_awaited()
    finally:
        current_tenant_id.reset(token)
    assert await _requests(db) == []


@pytest.mark.parametrize(
    "step_code", [DeleteExecutionStepCode.MINIO, DeleteExecutionStepCode.ES, DeleteExecutionStepCode.MILVUS]
)
async def test_empty_folder_cleanup_does_not_initialize_external_stores(step_code):
    context = MutationStepContext(
        tenant_id=42,
        request_id=1,
        execution_token="delete",
        action="delete",
        step_code=step_code,
        idempotency_key=f"delete:{step_code}",
        resource_type="folder",
        resource_id=1,
        applicant_user_id=5,
        source_space_id=128,
        target_space_id=None,
        manifest={"file_ids": [], "object_names": []},
    )
    result = await KnowledgeSpaceMutationExecutor._apply_delete_purge_step(context)
    assert result.result_digest == f"{step_code}:empty"


async def test_commit_acknowledgement_loss_keeps_recoverable_cleanup(direct_delete_db):
    db = direct_delete_db

    class SessionWithLostCommitAck:
        def __init__(self, session):
            self.session = session

        def __getattr__(self, name):
            return getattr(self.session, name)

        @asynccontextmanager
        async def begin(self):
            async with self.session.begin():
                yield
            raise ConnectionError("commit acknowledgement lost")

    @asynccontextmanager
    async def sessions():
        async with db.sessions() as session:
            yield SessionWithLostCommitAck(session)

    service = _service(db, dispatch_purge=AsyncMock())
    service.session_factory = sessions
    with pytest.raises(ConnectionError, match="acknowledgement lost"):
        await service.delete(resource=db.root, applicant_user_id=5)
    (request,) = await _requests(db)
    assert request.execution_checkpoint["deletion_cutover_active"] is True
    async with db.sessions() as session:
        assert await session.get(KnowledgeFile, db.root.id) is None
        candidates, _, _ = await KnowledgeSpaceFileChangeCompensationRepository(session).list_cleanup_candidates(
            tenant_id=42,
            after_request_id=0,
            now=datetime.now(UTC).replace(tzinfo=None),
            limit=20,
        )
    assert [row.request_id for row in candidates] == [request.id]
    service.dispatch_purge.assert_not_awaited()


async def test_pending_approval_conflict_blocks_direct_delete(direct_delete_db):
    db = direct_delete_db
    async with db.sessions() as session, session.begin():
        request = KnowledgeSpaceFileChangeRequest(
            tenant_id=42,
            space_id=db.space.id,
            action="move",
            resource_type="folder",
            resource_id=db.root.id,
            applicant_user_id=5,
            business_key="pending-move",
            request_fingerprint="pending-move",
            approval_instance_id=501,
        )
        session.add(request)
        await session.flush()
        session.add(
            KnowledgeSpaceFileChangeFootprint(
                tenant_id=42,
                request_id=request.id,
                space_id=db.space.id,
                resource_type="folder",
                resource_id=db.root.id,
                path_root=f"/{db.parent.id}/{db.root.id}/",
                lock_scope="subtree",
            )
        )
    dispatch = AsyncMock()
    with pytest.raises(SpaceFileChangeConflictError):
        await _service(db, dispatch_purge=dispatch).delete(resource=db.root, applicant_user_id=5)
    dispatch.assert_not_awaited()
    assert len(await _requests(db)) == 1
    async with db.sessions() as session:
        assert await session.get(KnowledgeFile, db.root.id)
        assert await session.get(KnowledgeFile, db.child.id)


async def test_folder_operation_commits_marker_before_cutover_and_resolves_only_matching_history(direct_delete_db):
    from bisheng.knowledge.domain.models.folder_deletion import marker_for
    from bisheng.knowledge.domain.services.knowledge_folder_deletion_service import KnowledgeFolderDeletionService

    db = direct_delete_db
    svc = KnowledgeFolderDeletionService(db.space.id, db.sessions)
    owner = SimpleNamespace(
        login_user=SimpleNamespace(user_id=5),
        _load_space_listing_scope=AsyncMock(return_value=(db.space, None)),
        _filter_visible_child_items=AsyncMock(side_effect=lambda rows, **kwargs: rows),
        _batch_actions=AsyncMock(return_value={str(db.space.id): {"visible"}}),
    )
    async with svc.track(db.root.id, 5) as token:
        async with db.sessions() as session:
            row = await session.get(KnowledgeFile, db.root.id)
            assert row.status == 8 and marker_for(row)["operation_id"] == token
            assert (await session.exec(select(KnowledgeSpaceFileChangeRequest))).all() == []
        with pytest.raises(SpaceFileChangeConflictError) as conflict:
            async with svc.track(db.root.id, 6):
                pytest.fail("duplicate claim succeeded")
        assert conflict.value.kwargs["operation_id"] == token
        await _service(db, dispatch_purge=AsyncMock()).delete(resource=db.root, applicant_user_id=5, operation_id=token)
    known = {db.root.id: token}
    (item,) = await svc.query(owner, [db.root.id], known)
    assert item.state == "succeeded" and item.operation_id == token
    owner.login_user.user_id = 6
    (item,) = await svc.query(owner, [db.root.id], known)
    assert item.state == "unavailable" and item.operation_id is None
    owner._batch_actions.return_value = {str(db.space.id): {"visible", "manage_permission"}}
    (item,) = await svc.query(owner, [db.root.id], {db.root.id: "wrong-token"})
    assert item.state == "untracked"
    async with db.sessions() as session, session.begin():
        from sqlalchemy import delete

        await session.exec(
            delete(KnowledgeSpaceFileChangeExecutionStep).where(
                KnowledgeSpaceFileChangeExecutionStep.step_code == DeleteExecutionStepCode.DB_CUTOVER
            )
        )
    (item,) = await svc.query(owner, [db.root.id], known)
    assert item.state == "untracked"


async def test_reconciled_root_fences_old_manifest_and_delayed_callbacks(direct_delete_db):
    from datetime import timedelta

    from bisheng.knowledge.domain.models.folder_deletion import RESERVED_KEY, marker_for
    from bisheng.knowledge.domain.services.knowledge_folder_deletion_service import KnowledgeFolderDeletionService

    db = direct_delete_db
    svc = KnowledgeFolderDeletionService(db.space.id, db.sessions)
    async with svc.track(db.root.id, 5) as token:
        async with db.sessions() as session, session.begin():
            row = await session.get(KnowledgeFile, db.root.id)
            marker = marker_for(row)
            row.user_metadata = {
                "preserved": "yes",
                RESERVED_KEY: {**marker, "heartbeat_at": (datetime.now(UTC) - timedelta(seconds=90)).isoformat()},
            }
        owner = SimpleNamespace(
            login_user=SimpleNamespace(user_id=6),
            _load_space_listing_scope=AsyncMock(return_value=(db.space, None)),
            _filter_visible_child_items=AsyncMock(side_effect=lambda rows, **kwargs: rows),
            _batch_actions=AsyncMock(return_value={str(db.space.id): {"visible"}}),
        )
        observed = await svc.reconcile(owner, db.root.id, token)
        assert observed.state == "unknown" and not observed.can_reconcile
        owner.login_user.user_id = 5
        observed = await svc.reconcile(owner, db.root.id, token)
        assert (observed.state, observed.failure_reason) == ("failed", "interrupted")
        async with svc.track(db.root.id, 5) as newer:
            assert newer != token
            with pytest.raises(SpaceFileChangeConflictError):
                await _service(db, dispatch_purge=AsyncMock()).delete(
                    resource=db.root, applicant_user_id=5, operation_id=token
                )
            assert not await svc._update(db.root.id, token, reason="delete_failed")
            async with db.sessions() as session:
                row = await session.get(KnowledgeFile, db.root.id)
                assert row.status == 8 and marker_for(row)["operation_id"] == newer
                assert row.user_metadata["preserved"] == "yes"
                assert await session.get(KnowledgeFile, db.child.id)
    assert await _requests(db) == []


async def test_folder_explicit_failure_clears_only_its_marker_and_commit_uncertainty_preserves_it(direct_delete_db):
    from bisheng.knowledge.domain.models.folder_deletion import marker_for
    from bisheng.knowledge.domain.services.knowledge_folder_deletion_service import (
        FolderCommitUncertain,
        KnowledgeFolderDeletionService,
        delete_transaction,
    )

    db = direct_delete_db
    svc = KnowledgeFolderDeletionService(db.space.id, db.sessions)
    with pytest.raises(PermissionError):
        async with svc.track(db.root.id, 5):
            raise PermissionError("subtree denied")
    async with db.sessions() as session:
        row = await session.get(KnowledgeFile, db.root.id)
        assert row.status == 2 and marker_for(row)["phase"] == "failed"

    @asynccontextmanager
    async def fail_commit():
        yield
        raise RuntimeError("commit was not acknowledged")

    with pytest.raises(FolderCommitUncertain):
        async with svc.track(db.root.id, 5) as token:
            async with delete_transaction(SimpleNamespace(begin=fail_commit), True):
                ...
    async with db.sessions() as session:
        row = await session.get(KnowledgeFile, db.root.id)
        assert row.status == 8 and marker_for(row)["operation_id"] == token


async def test_reconcile_busy_root_keeps_unknown_and_current_holder_can_commit(direct_delete_db, monkeypatch):
    from datetime import timedelta

    from bisheng.knowledge.domain.models.folder_deletion import RESERVED_KEY, marker_for
    from bisheng.knowledge.domain.repositories.knowledge_folder_deletion_repository import (
        FolderLockBusy,
        KnowledgeFolderDeletionRepository,
    )
    from bisheng.knowledge.domain.services.knowledge_folder_deletion_service import KnowledgeFolderDeletionService

    db = direct_delete_db
    svc = KnowledgeFolderDeletionService(db.space.id, db.sessions)
    async with svc.track(db.root.id, 5) as token:
        async with db.sessions() as session, session.begin():
            row = await session.get(KnowledgeFile, db.root.id)
            row.user_metadata = {
                RESERVED_KEY: {
                    **marker_for(row),
                    "heartbeat_at": (datetime.now(UTC) - timedelta(seconds=90)).isoformat(),
                }
            }
        owner = SimpleNamespace(
            login_user=SimpleNamespace(user_id=5),
            _load_space_listing_scope=AsyncMock(return_value=(db.space, None)),
            _filter_visible_child_items=AsyncMock(side_effect=lambda rows, **kwargs: rows),
            _batch_actions=AsyncMock(return_value={str(db.space.id): {"visible"}}),
        )
        with monkeypatch.context() as m:
            m.setattr(KnowledgeFolderDeletionRepository, "locked", AsyncMock(side_effect=FolderLockBusy()))
            assert not await svc._update(db.root.id, token)
            result = await svc.reconcile(owner, db.root.id, token)
            assert result.state == "unknown" and result.can_reconcile
        await _service(db, dispatch_purge=AsyncMock()).delete(resource=db.root, applicant_user_id=5, operation_id=token)
    (item,) = await svc.query(owner, [db.root.id], {db.root.id: token})
    assert item.state == "succeeded"


@pytest.mark.parametrize("grant_file_only", [False, True])
async def test_hidden_deleting_ancestor_is_observed_only_through_visible_anchor(direct_delete_db, grant_file_only):
    from bisheng.knowledge.domain.services.knowledge_folder_deletion_service import KnowledgeFolderDeletionService

    db = direct_delete_db
    leased = False

    @asynccontextmanager
    async def sessions():
        nonlocal leased
        async with db.sessions() as session:
            assert not leased
            leased = True
            try:
                yield session
            finally:
                leased = False

    svc = KnowledgeFolderDeletionService(db.space.id, sessions)
    allowed = {db.child.id} if grant_file_only else {db.root.id, db.child.id}

    async def visible(rows, **kwargs):
        assert not leased, "permission reads must not nest inside the business connection"
        return [row for row in rows if row.id in allowed]

    owner = SimpleNamespace(
        login_user=SimpleNamespace(user_id=6),
        _load_space_listing_scope=AsyncMock(return_value=(db.space, None)),
        _batch_actions=AsyncMock(return_value={}),
        _filter_visible_child_items=visible,
    )
    async with svc.track(db.parent.id, 5):
        result = [{}]
        await svc.project_page([db.child], result, None, owner=owner, space=db.space)
        alias = result[0]["deletion_status"]
        assert alias["root_folder_id"] == (db.child.id if grant_file_only else db.root.id)
        assert alias["operation_id"] is None and alias["state"] == "running"
        observed = await svc.query(owner, [alias["root_folder_id"], db.parent.id], {})
        assert observed[0].state == "running" and observed[0].operation_id is None and not observed[0].can_reconcile
        assert observed[1].state == "unavailable" and observed[1].operation_id is None


async def test_visible_folder_failure_details_are_private_to_initiator_and_manager(direct_delete_db):
    from bisheng.knowledge.domain.services.knowledge_folder_deletion_service import KnowledgeFolderDeletionService

    db = direct_delete_db
    svc = KnowledgeFolderDeletionService(db.space.id, db.sessions)
    owner = SimpleNamespace(
        login_user=SimpleNamespace(user_id=6),
        _load_space_listing_scope=AsyncMock(return_value=(db.space, None)),
        _batch_actions=AsyncMock(return_value={str(db.space.id): {"visible"}}),
        _filter_visible_child_items=AsyncMock(side_effect=lambda rows, **kwargs: rows),
    )
    with pytest.raises(PermissionError):
        async with svc.track(db.root.id, 5) as token:
            raise PermissionError("denied")
    (item,) = await svc.query(owner, [db.root.id], {})
    assert item.state == "idle" and not item.operation_id and not item.failure_reason
    (item,) = await svc.query(owner, [db.root.id], {db.root.id: token})
    assert item.state == "unavailable" and not item.operation_id and not item.failure_reason
