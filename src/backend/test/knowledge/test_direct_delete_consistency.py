"""SQL rollback, durable dispatch, leased recovery and external verification."""

from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge_space import SpaceFileNotFoundError
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_delete_job import KnowledgeSpaceDeleteJob, deletion_now
from bisheng.knowledge.domain.repositories.knowledge_space_delete_repository import KnowledgeSpaceDeleteRepository
from bisheng.knowledge.domain.services.knowledge_permission_service import KnowledgeFilePermissionRecord
from bisheng.knowledge.domain.services.knowledge_space_direct_delete_service import (
    DELETE_STEPS,
    KnowledgeSpaceDirectDeleteService,
    dispatch_delete_job,
)


@pytest.fixture
async def db():
    token = set_current_tenant_id(42)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            SQLModel.metadata.create_all,
            tables=[
                model.__table__
                for model in (
                    Knowledge,
                    KnowledgeFile,
                    KnowledgeDocument,
                    KnowledgeDocumentVersion,
                    KnowledgeSpaceDeleteJob,
                )
            ],
        )

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    async with sessions() as session, session.begin():
        space = Knowledge(id=8, tenant_id=42, name="space", type=3, index_name="space8", collection_name="space8")
        parent = KnowledgeFile(id=10, tenant_id=42, knowledge_id=8, user_id=5, file_name="keep", file_type=0)
        root = KnowledgeFile(
            id=20, tenant_id=42, knowledge_id=8, user_id=5, file_name="delete", file_type=0, file_level_path="/10"
        )
        child = KnowledgeFile(
            id=30,
            tenant_id=42,
            knowledge_id=8,
            user_id=5,
            file_name="new.pdf",
            file_level_path="/10/20",
            status=2,
            object_name="original/new.pdf",
        )
        sibling = KnowledgeFile(
            id=31,
            tenant_id=42,
            knowledge_id=8,
            user_id=5,
            file_name="old.pdf",
            file_level_path="/10",
            status=2,
            object_name="original/old.pdf",
        )
        neighbor = KnowledgeFile(
            id=40,
            tenant_id=42,
            knowledge_id=8,
            user_id=5,
            file_name="neighbor.pdf",
            file_level_path="/10/200",
            status=2,
        )
        document = KnowledgeDocument(id=50, knowledge_id=8, primary_version_id=61)
        versions = [
            KnowledgeDocumentVersion(id=60, document_id=50, knowledge_file_id=31, version_no=1),
            KnowledgeDocumentVersion(id=61, document_id=50, knowledge_file_id=30, version_no=2, is_primary=True),
        ]
        session.add_all([space, parent, root, child, sibling, neighbor, document, *versions])
    try:
        yield SimpleNamespace(sessions=sessions, root=root, child=child, sibling=sibling, parent=parent)
    finally:
        await engine.dispose()
        current_tenant_id.reset(token)


def service(db, **kwargs):
    async def records(resources):
        return [
            KnowledgeFilePermissionRecord(
                tenant_id=42,
                resource_type=kind,
                resource_id=str(rid),
                status="ACTIVE" if kind == "folder" else "SUCCESS",
                owner_user_id=5,
                permission_version=1,
                context_version="before-cutover",
                parent_type="folder",
                parent_id="10",
                mode="INHERIT",
            )
            for kind, rid in resources
        ]

    return KnowledgeSpaceDirectDeleteService(
        session_factory=db.sessions,
        authorize=kwargs.pop("authorize", AsyncMock()),
        load_permission_records=records,
        dispatch=kwargs.pop("dispatch", AsyncMock()),
        **kwargs,
    )


async def jobs(db):
    async with db.sessions() as session:
        return list((await session.exec(select(KnowledgeSpaceDeleteJob))).all())


async def retry_now(db, job_id):
    async with db.sessions() as session, session.begin():
        job = await session.get(KnowledgeSpaceDeleteJob, job_id)
        job.next_attempt_at = deletion_now() - timedelta(seconds=1)
        session.add(job)


async def test_cutover_commits_rows_versions_and_job_before_dispatch(db):
    async def dispatch(**kwargs):
        assert kwargs["tenant_id"] == 42
        async with db.sessions() as session:
            assert await session.get(KnowledgeFile, 20) is None
            assert await session.get(KnowledgeFile, 30) is None
            assert await session.get(KnowledgeFile, 31) is None
            assert await session.get(KnowledgeFile, 10)
            assert await session.get(KnowledgeFile, 40)
            assert await session.get(KnowledgeDocument, 50) is None
            assert (await session.exec(select(KnowledgeDocumentVersion))).all() == []
            assert (await session.get(KnowledgeSpaceDeleteJob, kwargs["job_id"])).state == "PENDING"

    svc = service(db, dispatch=AsyncMock(side_effect=dispatch))
    manifest = await svc.delete(resource=db.root, applicant_user_id=5)
    assert manifest["rows"] == [20, 30, 31]
    assert manifest["file_ids"] == [30, 31]
    assert manifest["folder_ids"] == [20]
    assert manifest["object_names"] == ["30", "31", "original/new.pdf", "original/old.pdf"]
    assert [call.args for call in svc.authorize.await_args_list] == [
        ("folder", 20, "delete"),
        ("knowledge_file", 30, "delete"),
        ("knowledge_file", 31, "delete"),
    ]
    svc.dispatch.assert_awaited_once()


async def test_db_failure_rolls_back_entire_graph_and_job_without_dispatch(db):
    class Failure(KnowledgeSpaceDeleteRepository):
        async def cutover(self, session, manifest):
            await super().cutover(session, manifest)
            raise RuntimeError("simulated database failure")

    svc = service(db, repository=Failure(db.sessions))
    with pytest.raises(RuntimeError, match="database failure"):
        await svc.delete(resource=db.root, applicant_user_id=5)
    async with db.sessions() as session:
        assert all([await session.get(KnowledgeFile, fid) for fid in [20, 30, 31]])
        assert await session.get(KnowledgeDocument, 50)
        assert len((await session.exec(select(KnowledgeDocumentVersion))).all()) == 2
    assert await jobs(db) == []
    svc.dispatch.assert_not_awaited()


async def test_expanded_version_sibling_permission_failure_leaves_everything_unchanged(db):
    async def authorize(kind, rid, action):
        if rid == 31:
            raise PermissionError("sibling is not deletable")

    svc = service(db, authorize=AsyncMock(side_effect=authorize))
    with pytest.raises(PermissionError):
        await svc.delete(resource=db.root, applicant_user_id=5)
    assert await jobs(db) == []
    async with db.sessions() as session:
        assert await session.get(KnowledgeFile, 20)
        assert await session.get(KnowledgeDocumentVersion, 61)
    svc.dispatch.assert_not_awaited()


async def test_broker_failure_keeps_recoverable_job(db):
    svc = service(db, dispatch=AsyncMock(side_effect=ConnectionError("broker offline")))
    await svc.delete(resource=db.root, applicant_user_id=5)
    (job,) = await jobs(db)
    assert await svc.repository.due_jobs() == [(42, job.id)]
    async with db.sessions() as session:
        assert await session.get(KnowledgeFile, 20) is None


async def test_missing_permission_snapshot_prevents_business_cutover(db):
    svc = service(db)
    svc.load_permission_records = AsyncMock(return_value=[])
    with pytest.raises(RuntimeError, match="snapshots"):
        await svc.delete(resource=db.root, applicant_user_id=5)
    assert await jobs(db) == []
    async with db.sessions() as session:
        assert await session.get(KnowledgeFile, 20)


async def test_finalize_requires_all_external_steps_in_order(db):
    svc = service(db)
    await svc.delete(resource=db.root, applicant_user_id=5)
    (job,) = await jobs(db)
    owned = await svc.repository.claim(job.id)
    with pytest.raises(RuntimeError, match="unverified"):
        await svc.repository.advance(owned, complete=True)
    with pytest.raises(RuntimeError, match="in order"):
        await svc.repository.advance(owned, step="es")
    assert (await jobs(db))[0].state == "RUNNING"


async def test_recovery_scan_routes_work_from_every_tenant(db):
    svc = service(db)
    await svc.delete(resource=db.root, applicant_user_id=5)
    (own,) = await jobs(db)
    async with db.sessions() as session, session.begin():
        foreign = KnowledgeSpaceDeleteJob(tenant_id=43, space_id=80, applicant_user_id=9, manifest={})
        session.add(foreign)
    assert set(await svc.repository.due_jobs()) == {(42, own.id), (43, foreign.id)}


async def test_lost_commit_ack_is_recovered_from_database_job(db):
    @asynccontextmanager
    async def lost_ack():
        async with db.sessions() as session:
            yield session
        raise ConnectionError("commit ack lost")

    svc = service(db)
    svc.session_factory = lost_ack
    with pytest.raises(ConnectionError, match="ack lost"):
        await svc.delete(resource=db.root, applicant_user_id=5)
    (job,) = await jobs(db)
    assert await svc.repository.due_jobs() == [(42, job.id)]
    svc.dispatch.assert_not_awaited()


async def test_delete_historical_version_keeps_primary_and_document(db):
    await service(db).delete(resource=db.sibling, applicant_user_id=5)
    async with db.sessions() as session:
        assert await session.get(KnowledgeFile, 31) is None
        assert await session.get(KnowledgeDocumentVersion, 60) is None
        assert await session.get(KnowledgeFile, 30)
        assert await session.get(KnowledgeDocumentVersion, 61)
        assert (await session.get(KnowledgeDocument, 50)).primary_version_id == 61


async def test_tenant_mismatch_cannot_delete_or_claim(db):
    svc = service(db)
    await svc.delete(resource=db.root, applicant_user_id=5)
    (job,) = await jobs(db)
    token = set_current_tenant_id(43)
    try:
        with pytest.raises(LookupError):
            await svc.repository.claim(job.id)
        with pytest.raises(SpaceFileNotFoundError):
            await svc.delete(resource=db.parent, applicant_user_id=5)
    finally:
        current_tenant_id.reset(token)
    assert (await jobs(db))[0].state == "PENDING"


async def test_duplicate_worker_cannot_claim_active_lease_and_old_token_cannot_finalize(db):
    svc = service(db)
    await svc.delete(resource=db.root, applicant_user_id=5)
    (job,) = await jobs(db)
    old = await svc.repository.claim(job.id)
    assert await svc.repository.claim(job.id) is None
    assert await svc.repository.due_jobs() == []
    async with db.sessions() as session, session.begin():
        row = await session.get(KnowledgeSpaceDeleteJob, job.id)
        row.lease_until = deletion_now() - timedelta(seconds=1)
        session.add(row)
    assert await svc.repository.due_jobs() == [(42, job.id)]
    newer = await svc.repository.claim(job.id)
    assert newer.lease_token != old.lease_token
    with pytest.raises(RuntimeError, match="lease was replaced"):
        await svc.repository.advance(old, complete=True)
    assert (await jobs(db))[0].lease_token == newer.lease_token


async def test_partial_purge_failure_retries_from_checkpoint_in_new_service(db):
    calls = []
    failed = False

    async def purge_step(step, job):
        nonlocal failed
        calls.append(step)
        if step == "minio" and not failed:
            failed = True
            raise ConnectionError("MinIO offline")

    svc = service(db, purge_step=purge_step)
    await svc.delete(resource=db.root, applicant_user_id=5)
    (job,) = await jobs(db)
    with pytest.raises(ConnectionError):
        await svc.purge(job.id)
    (failed_job,) = await jobs(db)
    assert failed_job.state == "PENDING"
    assert failed_job.completed_steps == ["fga"]
    assert failed_job.last_error == "MinIO offline"
    await retry_now(db, job.id)
    await service(db, purge_step=purge_step).purge(job.id)
    (completed,) = await jobs(db)
    assert calls == ["fga", "minio", "minio", "es", "milvus"]
    assert completed.state == "SUCCEEDED"
    assert completed.completed_steps == list(DELETE_STEPS)
    assert completed.last_error is None
    assert await svc.purge(job.id) is False
    async with db.sessions() as session:
        assert await session.get(KnowledgeFile, 20) is None


async def test_empty_folder_cleanup_uses_snapshot_without_storage_or_embedding(db):
    await service(db).delete(resource=db.parent, applicant_user_id=5)
    # Seed a separate empty-folder job to exercise the real cleanup owner.
    async with db.sessions() as session, session.begin():
        folder = KnowledgeFile(id=99, tenant_id=42, knowledge_id=8, user_id=5, file_name="empty", file_type=0)
        session.add(folder)
    svc = service(db)
    await svc.delete(resource=folder, applicant_user_id=5)
    job = next(row for row in await jobs(db) if row.manifest["rows"] == [99])
    adapter = SimpleNamespace(project_delete=AsyncMock())
    with (
        patch("bisheng.permission.application.access.get_f048_resource_adapter", AsyncMock(return_value=adapter)),
        patch(
            "bisheng.core.storage.minio.minio_manager.get_minio_storage",
            AsyncMock(side_effect=AssertionError("storage not needed")),
        ),
        patch(
            "bisheng.knowledge.domain.knowledge_rag.KnowledgeRag.init_knowledge_milvus_vectorstore_sync",
            side_effect=AssertionError("embedding not needed"),
        ),
    ):
        assert await svc.purge(job.id)
    assert adapter.project_delete.await_args.kwargs["record"].resource_id == "99"


@pytest.mark.parametrize("step", ["minio", "es", "milvus"])
async def test_external_step_cannot_complete_with_residue(db, step):
    svc = service(db)
    await svc.delete(resource=db.root, applicant_user_id=5)
    (job,) = await jobs(db)
    job = await svc.repository.claim(job.id)
    minio = SimpleNamespace(bucket="bisheng", remove_object=AsyncMock(), object_exists=AsyncMock(return_value=True))
    es = SimpleNamespace(
        client=SimpleNamespace(
            indices=SimpleNamespace(exists=MagicMock(return_value=True), refresh=MagicMock()),
            delete_by_query=MagicMock(return_value={"failures": []}),
            count=MagicMock(return_value={"count": 1}),
        )
    )
    milvus = SimpleNamespace(
        col=SimpleNamespace(delete=MagicMock(), flush=MagicMock(), query=MagicMock(return_value=[{"count(*)": 1}]))
    )
    with (
        patch("bisheng.core.storage.minio.minio_manager.get_minio_storage", AsyncMock(return_value=minio)),
        patch(
            "bisheng.knowledge.domain.knowledge_rag.KnowledgeRag.init_knowledge_es_vectorstore_sync", return_value=es
        ),
        patch(
            "bisheng.knowledge.domain.knowledge_rag.KnowledgeRag.init_knowledge_milvus_vectorstore_sync",
            return_value=milvus,
        ),
    ):
        with pytest.raises(RuntimeError, match="left"):
            await svc._purge_step(step, job)


async def test_dispatch_carries_explicit_tenant_header(monkeypatch):
    import sys

    publish = MagicMock()
    monkeypatch.setitem(
        sys.modules,
        "bisheng.worker.knowledge.space_delete",
        SimpleNamespace(purge_space_delete=SimpleNamespace(apply_async=publish)),
    )
    await dispatch_delete_job(tenant_id=42, job_id="durable-job")
    publish.assert_called_once_with(
        kwargs={"job_id": "durable-job"}, headers={"tenant_id": 42, "f048_permission_task": True}
    )
