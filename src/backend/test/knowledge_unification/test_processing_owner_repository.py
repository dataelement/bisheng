"""T642: actual document/version/file joins define processing scope."""

from dataclasses import replace

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.common.errcode.knowledge_space import SpaceNotFoundError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.core.database import tenant_filter
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.models.knowledge_processing_retry import KnowledgeProcessingRetryReceipt
from bisheng.knowledge.domain.repositories.processing_job_repository import (
    NewProcessingItem,
    ProcessingConfiguration,
    ProcessingJobRepository,
)
from bisheng.knowledge.domain.repositories.processing_owner_repository import ProcessingOwnerRepository


@pytest.fixture
def scope_tenant(tenant_context, monkeypatch):
    tenant_context(101)
    names = tenant_filter._tenant_aware_tables | {"knowledge", "knowledgefile"}
    monkeypatch.setattr(tenant_filter, "_force_import_all_models", lambda: None)
    monkeypatch.setattr(tenant_filter, "_discover_tenant_aware_tables", lambda: names)
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", names)
    tenant_filter.register_tenant_filter_events()


@pytest.fixture
async def scope_session(scope_tenant):
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda conn: SQLModel.metadata.create_all(
                conn,
                tables=[
                    model.__table__ for model in (Knowledge, KnowledgeFile, KnowledgeDocument, KnowledgeDocumentVersion)
                ],
            )
        )
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add_all(
            [
                Knowledge(id=1, tenant_id=101, user_id=7, name="one", type=3),
                Knowledge(id=2, tenant_id=202, user_id=8, name="foreign", type=3),
                KnowledgeFile(
                    id=8,
                    tenant_id=101,
                    knowledge_id=1,
                    file_name="first",
                    file_level_path="/3/4",
                    split_rule='{"chunk_size":256}',
                ),
                KnowledgeFile(id=9, tenant_id=101, knowledge_id=1, file_name="history"),
                KnowledgeFile(id=10, tenant_id=101, knowledge_id=1, file_name="second"),
                KnowledgeFile(id=80, tenant_id=202, knowledge_id=2, file_name="foreign"),
                KnowledgeDocument(id=10, knowledge_id=1, primary_version_id=100),
                KnowledgeDocument(id=11, knowledge_id=1, primary_version_id=102),
                KnowledgeDocument(id=20, knowledge_id=2, primary_version_id=200),
                KnowledgeDocumentVersion(id=100, document_id=10, knowledge_file_id=8, version_no=1, is_primary=True),
                KnowledgeDocumentVersion(id=101, document_id=10, knowledge_file_id=9, version_no=2, is_primary=False),
                KnowledgeDocumentVersion(id=102, document_id=11, knowledge_file_id=10, version_no=1, is_primary=True),
                KnowledgeDocumentVersion(id=200, document_id=20, knowledge_file_id=80, version_no=1, is_primary=True),
            ]
        )
        await session.commit()
        yield session
    await engine.dispose()


async def test_all_versions_use_true_keys_without_cartesian_product(scope_session):
    rows = await ProcessingOwnerRepository().aload_scope(scope_session, 1, for_update=True)
    assert [(row.target.file_id, row.target.document_id, row.target.version_id) for row in rows] == [
        (8, 10, 100),
        (9, 10, 101),
        (10, 11, 102),
    ]
    assert [row.is_primary for row in rows] == [True, False, True]
    assert rows[0].parent_id == 4 and rows[0].split_rule == '{"chunk_size":256}'
    assert not any(row.target.file_id == 80 for row in rows)


async def test_explicit_version_scope_is_exact_and_document_id_cannot_rebind(scope_session):
    repo = ProcessingOwnerRepository()
    rows = await repo.aload_scope(scope_session, 1, targets=[{"file_id": 9, "version_id": 101}])
    assert len(rows) == 1 and rows[0].target.document_id == 10
    for wrong in [
        {"file_id": 8, "version_id": 101},
        {"file_id": 9, "version_id": 101, "document_id": 11},
        {"file_id": 80, "version_id": 200},
    ]:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.aload_scope(scope_session, 1, targets=[wrong], for_update=True)
    assert await repo.aload_scope(scope_session, 1, targets=[]) == ()


async def test_current_tenant_is_not_inferred_from_requested_space(scope_session):
    with pytest.raises(SpaceNotFoundError):
        await ProcessingOwnerRepository().aload_scope(scope_session, 2)
    with tenant_execution_scope(202):
        with pytest.raises(SpaceNotFoundError):
            await ProcessingOwnerRepository().aload_scope(scope_session, 1)
        rows = await ProcessingOwnerRepository().aload_scope(scope_session, 2)
        assert [row.target.file_id for row in rows] == [80]


async def test_scope_is_fresh_and_borrowed_session_is_not_committed(scope_session):
    repo = ProcessingOwnerRepository()
    before = await repo.aload_scope(scope_session, 1)
    physical = await scope_session.get(KnowledgeFile, 8)
    physical.file_name = "not committed"
    await scope_session.flush()
    changed = await repo.aload_scope(scope_session, 1, for_update=True)
    assert changed[0].revision != before[0].revision
    await scope_session.rollback()
    rows = await repo.aload_scope(scope_session, 1)
    assert rows[0].file_name == "first" and rows[0].revision == before[0].revision


async def test_broken_version_link_does_not_silently_reduce_full_scope(scope_session):
    version = await scope_session.get(KnowledgeDocumentVersion, 100)
    version.knowledge_file_id = 80
    await scope_session.flush()
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await ProcessingOwnerRepository().aload_scope(scope_session, 1)


async def leased_file(session):
    file = await session.get(KnowledgeFile, 8)
    file.status = 2
    await session.flush()
    connection = await session.connection()
    await connection.run_sync(
        lambda active: SQLModel.metadata.create_all(
            active,
            tables=[
                model.__table__
                for model in (KnowledgeProcessingJob, KnowledgeProcessingItem, KnowledgeProcessingRetryReceipt)
            ],
        )
    )
    repo = ProcessingOwnerRepository()
    records = await repo.aload_scope(session, 1, targets=[{"file_id": 8, "version_id": 100}])
    jobs = ProcessingJobRepository()
    configuration = ProcessingConfiguration(0, None)
    created = await jobs.acreate(
        session,
        space_id=1,
        kind="embedding_rebuild",
        idempotency_key="status",
        actor_user_id=7,
        actor_reference={"actor_id": 7},
        parameters={},
        configuration=configuration,
        items=[NewProcessingItem(target=records[0].target, expected_space_id=1, expected_parent_id=4)],
    )
    job_lease = await jobs.aclaim(session, created.job.id, configuration=configuration)
    claimed = await jobs.aclaim_next_item(session, job_lease, configuration=configuration)
    await session.commit()
    return repo, jobs, claimed.lease


@pytest.mark.parametrize("succeeded", [True, False])
async def test_file_status_and_item_completion_share_guarded_transaction(scope_session, succeeded):
    repo, jobs, lease = await leased_file(scope_session)
    assert await repo.acomplete_file(scope_session, lease, jobs=jobs, succeeded=succeeded, error_code=10915)
    assert (await scope_session.exec(select(KnowledgeFile.status).where(KnowledgeFile.id == 8))).one() == (
        2 if succeeded else 3
    )
    item = await scope_session.get(KnowledgeProcessingItem, lease.item_id)
    assert item.state == ("succeeded" if succeeded else "failed")
    await scope_session.rollback()
    assert (await scope_session.exec(select(KnowledgeFile.status).where(KnowledgeFile.id == 8))).one() == 2
    await scope_session.refresh(item)
    assert item.state == "running"


@pytest.mark.parametrize("invalid", ["lease", "generation", "parent", "unsafe", "inflight"])
async def test_stale_or_rebound_item_cannot_write_file_status(scope_session, invalid):
    repo, jobs, lease = await leased_file(scope_session)
    if invalid == "lease":
        lease = replace(lease, lease_token="old")
        assert not await repo.acomplete_file(scope_session, lease, jobs=jobs, succeeded=True)
    elif invalid == "generation":
        root = await scope_session.get(Knowledge, 1)
        root.model_config_revision += 1
        await scope_session.flush()
        assert not await repo.acomplete_file(scope_session, lease, jobs=jobs, succeeded=True)
        assert (await jobs.aget(scope_session, lease.job.job_id)).state == "obsolete"
    elif invalid == "parent":
        file = await scope_session.get(KnowledgeFile, 8)
        file.file_level_path = "/3/5"
        await scope_session.flush()
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.acomplete_file(scope_session, lease, jobs=jobs, succeeded=True)
    else:
        file = await scope_session.get(KnowledgeFile, 8)
        file.status = 7 if invalid == "unsafe" else 1
        await scope_session.flush()
        from bisheng.common.errcode.knowledge import KnowledgeProcessingConflictError

        with pytest.raises(KnowledgeProcessingConflictError):
            await repo.acomplete_file(scope_session, lease, jobs=jobs, succeeded=True)
        assert (
            await scope_session.exec(select(KnowledgeFile.status).where(KnowledgeFile.id == 8))
        ).one() == file.status
        return
    assert (await scope_session.exec(select(KnowledgeFile.status).where(KnowledgeFile.id == 8))).one() == 2
