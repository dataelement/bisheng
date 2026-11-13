"""正常manager关联: 使用真实仓储和隔离SQLite, 不连接环境数据库。"""

import sys
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlmodel import select

from bisheng.common.errcode.knowledge_space import KnowledgeDocumentEntryConflictError, SpacePermissionDeniedError
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.services.knowledge_document_distribution_service import (
    KnowledgeDocumentDistributionService,
)
from bisheng.knowledge.domain.services.knowledge_document_entry_resolver import KnowledgeDocumentEntryResolver
from bisheng.knowledge.domain.services.knowledge_document_permission_activation_service import (
    KnowledgeDocumentPermissionActivationService,
)
from test.knowledge.test_document_projection_batch_worker import worker as _projection_worker_fixture
from test.knowledge.test_knowledge_version_service_link import _build_svc, _seed_doc
from test.knowledge.test_knowledge_version_service_link import enable_switch as enable_switch

projection_worker = _projection_worker_fixture


async def seed_managers(session, *, target_history=False):
    target, target_v = await _seed_doc(session, 1, 100, "report.doc", md5="old")
    source, source_v = await _seed_doc(session, 1, 101, "report-new.doc", md5="new")
    for doc, file_id, generation in ((target, 100, 8), (source, 101, 13)):
        doc.content_generation = generation
        file = await session.get(KnowledgeFile, file_id)
        file.reference_document_id = doc.id
        file.entry_type = "manager"
        file.entry_status = "active"
        file.projection_status = "ready"
        file.desired_content_generation = file.applied_content_generation = generation
        file.desired_entry_generation = file.applied_entry_generation = 1
        file.user_id = file_id
        file.object_name = f"objects/{file_id}.doc"
        file.file_level_path = f"/{file_id}"
        file.level = 1
        file.original_uploader_id = file_id + 1000
        file.original_knowledge_id = 1
        file.belonging_organization_id = file_id + 2000
        session.add(file)
        session.add(doc)
    if target_history:
        session.add(
            KnowledgeFile(id=102, tenant_id=1, knowledge_id=1, file_name="history.doc", status=2, md5="history")
        )
        session.add(
            KnowledgeDocumentVersion(document_id=target.id, knowledge_file_id=102, version_no=2, is_primary=False)
        )
    await session.commit()
    return SimpleNamespace(target=target.id, source=source.id, target_version=target_v.id, source_version=source_v.id)


def service(session, monkeypatch, *, denied_file=None):
    svc = _build_svc(session)
    # 仅替换外部消息发布, 全文意图仍由真实事务写入SQLite。
    monkeypatch.setitem(
        sys.modules,
        "bisheng.worker.knowledge.fulltext_index",
        SimpleNamespace(
            publish_knowledge_fulltext_batch=MagicMock(),
            publish_knowledge_fulltext_outbox=MagicMock(),
        ),
    )

    async def permissions(file_id, space_id):
        return set() if file_id == denied_file else {"view_file", "rename_file", "delete_file", "upload_file"}

    svc.document_entry_resolver = KnowledgeDocumentEntryResolver(
        document_repository=svc.doc_repo,
        version_repository=svc.version_repo,
        file_repository=svc.knowledge_file_repo,
        permission_loader=permissions,
    )
    svc.document_distribution_service = KnowledgeDocumentDistributionService(
        session=session,
        document_repository=svc.doc_repo,
        version_repository=svc.version_repo,
        file_repository=svc.knowledge_file_repo,
        permission_activation_service=KnowledgeDocumentPermissionActivationService(
            file_repository=svc.knowledge_file_repo, tuple_writer=AsyncMock()
        ),
        permission_snapshot_loader=AsyncMock(return_value=[]),
    )
    svc._notify_favorite_version_changed = AsyncMock()
    svc._enqueue_document_distribution_projection = AsyncMock()
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_audit_telemetry_service."
        "KnowledgeAuditTelemetryService.audit_link_file_version",
        MagicMock(),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_version_service.KnowledgeSpaceContentStat.enqueue_file_stat_async",
        AsyncMock(),
    )
    return svc


async def rows(session, model):
    return (await session.exec(select(model).execution_options(populate_existing=True))).all()


@pytest.mark.parametrize("target_history", [False, True])
async def test_manager_link_transitions_the_entire_canonical_document(
    enable_switch, async_db_session, monkeypatch, target_history
):
    session = async_db_session
    seeded = await seed_managers(session, target_history=target_history)
    svc = service(session, monkeypatch)
    result = await svc.link_file_to_document(101, seeded.target)
    assert result.document_id == seeded.target and result.new_version_no == (3 if target_history else 2)
    files = {file.id: file for file in await rows(session, KnowledgeFile)}
    docs = {doc.id: doc for doc in await rows(session, KnowledgeDocument)}
    versions = {v.id: v for v in await rows(session, KnowledgeDocumentVersion)}
    assert versions[seeded.source_version].document_id == seeded.target
    assert versions[seeded.source_version].is_primary
    assert not versions[seeded.target_version].is_primary
    assert docs[seeded.target].primary_version_id == seeded.source_version
    assert docs[seeded.target].content_generation == 14
    assert docs[seeded.target].file_level_path == "/101"
    assert files[101].reference_document_id == seeded.target
    assert files[101].entry_type == "manager" and files[101].entry_status == "active"
    assert files[101].desired_content_generation == 14 and files[101].applied_content_generation == 0
    assert files[101].projection_status == "pending"
    assert files[101].original_uploader_id == 1100 and files[101].belonging_organization_id == 2100
    assert files[100].entry_type is None and files[100].reference_document_id is None
    for file_id in (100, 101):
        assert files[file_id].object_name == f"objects/{file_id}.doc"
        assert files[file_id].user_id == file_id and files[file_id].file_level_path == f"/{file_id}"
    assert docs[seeded.source].lifecycle_status == "invalid"
    assert docs[seeded.source].primary_version_id is None
    tombstones = [file for file in files.values() if file.entry_type == "projection_tombstone"]
    assert len(tombstones) == 1
    assert tombstones[0].reference_document_id == seeded.source and tombstones[0].entry_status == "deleting"
    assert tombstones[0].object_name is None and tombstones[0].file_size == 0
    svc._enqueue_document_distribution_projection.assert_awaited_once_with(
        tenant_id=1, entry_ids=[101, tombstones[0].id]
    )
    again = await svc.link_file_to_document(101, seeded.target)
    assert again == result
    assert len(await rows(session, KnowledgeDocumentVersion)) == len(versions)
    assert (await svc.doc_repo.find_by_id(seeded.target)).content_generation == 14
    assert len([file for file in await rows(session, KnowledgeFile) if file.entry_type == "projection_tombstone"]) == 1
    assert svc._enqueue_document_distribution_projection.await_count == 1


@pytest.mark.parametrize("denied_file", [100, 101])
async def test_manager_link_requires_edit_permission_on_both_files(
    enable_switch, async_db_session, monkeypatch, denied_file
):
    seeded = await seed_managers(async_db_session)
    svc = service(async_db_session, monkeypatch, denied_file=denied_file)
    with pytest.raises(SpacePermissionDeniedError):
        await svc.link_file_to_document(101, seeded.target)
    assert len(await rows(async_db_session, KnowledgeFile)) == 2
    assert (await svc.version_repo.find_by_knowledge_file_id(101)).document_id == seeded.source


@pytest.mark.parametrize("case", ["source_share", "target_share", "source_busy", "target_predecessor", "deleted"])
async def test_manager_link_rejects_unsafe_state_without_writing(enable_switch, async_db_session, monkeypatch, case):
    seeded = await seed_managers(async_db_session)
    session = async_db_session
    if case.endswith("share"):
        session.add(
            KnowledgeFile(
                id=103,
                tenant_id=1,
                knowledge_id=2,
                file_name="share.doc",
                status=2,
                reference_document_id=seeded.source if case == "source_share" else seeded.target,
                entry_type="share",
                entry_status="active",
            )
        )
    elif case == "source_busy":
        file = await session.get(KnowledgeFile, 101)
        file.projection_lease_owner = "inflight"
        session.add(file)
    elif case == "deleted":
        file = await session.get(KnowledgeFile, 101)
        file.deleted_at = datetime(2026, 11, 13)
        session.add(file)
    else:
        doc = await session.get(KnowledgeDocument, seeded.target)
        doc.predecessor_logic_file_id = 999
        session.add(doc)
    await session.commit()
    before = [file.model_dump() for file in await rows(session, KnowledgeFile)]
    svc = service(session, monkeypatch)
    with pytest.raises(KnowledgeDocumentEntryConflictError):
        await svc.link_file_to_document(101, seeded.target)
    assert [file.model_dump() for file in await rows(session, KnowledgeFile)] == before
    assert (await svc.doc_repo.find_by_id(seeded.target)).content_generation == 8


async def test_manager_link_rolls_back_all_state_on_commit_failure(enable_switch, async_db_session, monkeypatch):
    seeded = await seed_managers(async_db_session)
    svc = service(async_db_session, monkeypatch)
    svc.document_distribution_service._commit = AsyncMock(side_effect=RuntimeError("commit failed"))
    with pytest.raises(RuntimeError, match="commit failed"):
        await svc.link_file_to_document(101, seeded.target)
    files = {file.id: file for file in await rows(async_db_session, KnowledgeFile)}
    assert len(files) == 2 and files[101].reference_document_id == seeded.source
    assert files[100].entry_type == "manager" and files[101].entry_type == "manager"
    assert (await svc.doc_repo.find_by_id(seeded.source)).lifecycle_status == "active"
    assert (await svc.doc_repo.find_by_id(seeded.target)).content_generation == 8
    svc._enqueue_document_distribution_projection.assert_not_awaited()


async def test_manager_merge_uses_the_same_canonical_lifecycle(enable_switch, async_db_session, monkeypatch):
    seeded = await seed_managers(async_db_session)
    svc = service(async_db_session, monkeypatch)
    result = await svc.merge_source_document_into_current(100, seeded.source, force=True)
    assert result.document_id == seeded.target and result.new_version_no == 2
    assert (await svc.knowledge_file_repo.find_by_id(101)).reference_document_id == seeded.target
    assert (await svc.knowledge_file_repo.find_by_id(100)).reference_document_id is None
    assert (await svc.doc_repo.find_by_id(seeded.source)).lifecycle_status == "invalid"


@pytest.mark.parametrize("case", ["duplicate", "source_multi", "cross_space", "cross_tenant", "missing_primary"])
async def test_manager_link_keeps_document_boundary_guards(enable_switch, async_db_session, monkeypatch, case):
    from fastapi import HTTPException

    from bisheng.common.errcode.knowledge_space import (
        KnowledgeDocumentStateConflictError,
        VersionLinkSourceMultiVersionError,
        VersionLinkTargetUnavailableError,
    )

    session = async_db_session
    seeded = await seed_managers(session)
    expected = KnowledgeDocumentEntryConflictError
    if case == "duplicate":
        file = await session.get(KnowledgeFile, 101)
        file.md5 = "old"
        session.add(file)
    elif case == "source_multi":
        session.add(KnowledgeFile(id=104, knowledge_id=1, file_name="history.doc", status=2))
        session.add(
            KnowledgeDocumentVersion(document_id=seeded.source, knowledge_file_id=104, version_no=2, is_primary=False)
        )
        expected = VersionLinkSourceMultiVersionError
    else:
        doc = await session.get(KnowledgeDocument, seeded.target)
        if case == "cross_space":
            doc.knowledge_id = 2
            expected = HTTPException
        elif case == "cross_tenant":
            doc.tenant_id = 2
            expected = KnowledgeDocumentStateConflictError
        else:
            doc.primary_version_id = 9999
            expected = VersionLinkTargetUnavailableError
        session.add(doc)
    await session.commit()
    svc = service(session, monkeypatch)
    with pytest.raises(expected):
        await svc.link_file_to_document(101, seeded.target)
    assert (await svc.version_repo.find_by_knowledge_file_id(101)).document_id == seeded.source
    assert not any(file.entry_type == "projection_tombstone" for file in await rows(session, KnowledgeFile))


async def test_manager_link_rejects_generation_drift_after_permission_check(
    enable_switch, async_db_session, monkeypatch
):
    seeded = await seed_managers(async_db_session)
    svc = service(async_db_session, monkeypatch)
    original = svc.document_distribution_service.link_independent_managers

    async def drift(**kwargs):
        doc = await async_db_session.get(KnowledgeDocument, seeded.target)
        doc.content_generation += 1
        async_db_session.add(doc)
        await async_db_session.commit()
        return await original(**kwargs)

    svc.document_distribution_service.link_independent_managers = drift
    with pytest.raises(KnowledgeDocumentEntryConflictError):
        await svc.link_file_to_document(101, seeded.target)
    assert (await svc.version_repo.find_by_knowledge_file_id(101)).document_id == seeded.source
    assert (await svc.doc_repo.find_by_id(seeded.target)).content_generation == 9


async def test_manager_link_projection_can_retry_and_remove_only_the_retired_document(
    enable_switch, async_db_session, monkeypatch, projection_worker
):
    from bisheng.knowledge.domain.contracts.shared_space_storage import (
        ContentProjectionIdentity,
        ContentUpsertRequest,
        SharedContentChunk,
    )
    from bisheng.knowledge.domain.services.knowledge_document_projection_service import (
        KnowledgeDocumentProjectionService,
    )
    from test.fakes.shared_storage_fakes import FakeSharedSpaceStorageWriter

    session = async_db_session

    @asynccontextmanager
    async def db():
        yield session

    monkeypatch.setattr(projection_worker, "get_async_db_session", db)
    monkeypatch.setattr(projection_worker, "_delete_entry_permissions", AsyncMock())
    seeded = await seed_managers(session)
    svc = service(session, monkeypatch)
    writer = FakeSharedSpaceStorageWriter()
    for doc_id, version_id, file_id, generation in (
        (seeded.target, seeded.target_version, 100, 8),
        (seeded.source, seeded.source_version, 101, 13),
    ):
        await writer.upsert_content(
            ContentUpsertRequest(
                identity=ContentProjectionIdentity(
                    tenant_id=1,
                    canonical_document_id=doc_id,
                    canonical_version_id=version_id,
                    content_file_id=file_id,
                    content_generation=generation,
                    embedding_model_id="4",
                ),
                knowledge_ids=(1,),
                chunks=[SharedContentChunk(chunk_index=0, text="old")],
            )
        )
    await svc.link_file_to_document(101, seeded.target)
    loader = AsyncMock(side_effect=[RuntimeError("index unavailable"), [SharedContentChunk(chunk_index=0, text="new")]])
    projector = KnowledgeDocumentProjectionService(
        session=session,
        file_repository=svc.knowledge_file_repo,
        document_repository=svc.doc_repo,
        version_repository=svc.version_repo,
        shared_storage_writer=writer,
        shared_content_chunk_loader=loader,
        shared_embedding_model_id="4",
        deleting_entry_finalizer=projection_worker._finalize_deleting_entry,
    )
    with pytest.raises(RuntimeError, match="index unavailable"):
        await projector.process_entry(tenant_id=1, entry_id=101, lease_owner="first")
    failed = await svc.knowledge_file_repo.find_by_id(101)
    assert failed.reference_document_id == seeded.target and failed.projection_status == "failed"
    failed.projection_next_retry_at = None
    session.add(failed)
    await session.commit()
    result = await projector.process_entry(tenant_id=1, entry_id=101, lease_owner="retry")
    assert result.status == "ready"
    assert writer.content[(1, seeded.target, seeded.source_version, 14)][0]["text"] == "new"
    tombstone = next(file for file in await rows(session, KnowledgeFile) if file.entry_type == "projection_tombstone")
    result = await projector.process_entry(tenant_id=1, entry_id=tombstone.id, lease_owner="cleanup")
    assert result.status == "cleaned"
    assert not any(key[1] == seeded.source for key in writer.content)
    assert await svc.doc_repo.find_by_id(seeded.source) is None
    assert await svc.knowledge_file_repo.find_by_id(tombstone.id) is None
    assert (await svc.knowledge_file_repo.find_by_id(101)).object_name == "objects/101.doc"
    assert (await svc.knowledge_file_repo.find_by_id(100)).object_name == "objects/100.doc"


@pytest.mark.parametrize("remaining", ["entry", "version"])
async def test_cleanup_keeps_invalid_document_with_remaining_business_records(
    enable_switch, async_db_session, monkeypatch, projection_worker, remaining
):
    seeded = await seed_managers(async_db_session)
    svc = service(async_db_session, monkeypatch)
    document = await svc.doc_repo.find_by_id(seeded.source)
    document.lifecycle_status = "invalid"
    document.primary_version_id = None
    async_db_session.add(document)
    if remaining == "version":
        physical = await svc.knowledge_file_repo.find_by_id(101)
        physical.reference_document_id = physical.entry_type = physical.entry_status = None
        async_db_session.add(physical)
    cleanup = KnowledgeFile(
        id=300,
        tenant_id=1,
        knowledge_id=1,
        file_name="cleanup",
        reference_document_id=seeded.source,
        entry_type="projection_tombstone",
        entry_status="deleting",
        projection_status="ready",
        projection_lease_owner="cleanup",
        desired_content_generation=14,
        applied_content_generation=14,
        desired_entry_generation=1,
        applied_entry_generation=1,
    )
    async_db_session.add(cleanup)
    await async_db_session.commit()

    @asynccontextmanager
    async def db():
        yield async_db_session

    monkeypatch.setattr(projection_worker, "get_async_db_session", db)
    monkeypatch.setattr(projection_worker, "_delete_entry_permissions", AsyncMock())
    await projection_worker._finalize_deleting_entry(cleanup.model_copy())
    assert await svc.doc_repo.find_by_id(seeded.source) is not None
    assert await svc.knowledge_file_repo.find_by_id(101) is not None
    assert await svc.knowledge_file_repo.find_by_id(300) is None


async def test_broker_failure_leaves_durable_projection_work(enable_switch, async_db_session, monkeypatch):
    from bisheng.knowledge.domain.services.knowledge_document_projection_service import (
        KnowledgeDocumentProjectionService,
    )

    seeded = await seed_managers(async_db_session)
    svc = service(async_db_session, monkeypatch)
    svc._enqueue_document_distribution_projection = type(svc)._enqueue_document_distribution_projection.__get__(svc)
    monkeypatch.setitem(
        sys.modules,
        "bisheng.worker.knowledge.document_projection",
        SimpleNamespace(
            enqueue_document_projection_entries=MagicMock(side_effect=RuntimeError("broker unavailable")),
        ),
    )
    result = await svc.link_file_to_document(101, seeded.target)
    assert result.new_version_no == 2
    projector = KnowledgeDocumentProjectionService(session=async_db_session, file_repository=svc.knowledge_file_repo)
    due = await projector.list_due_entry_ids()
    tombstone = next(
        file for file in await rows(async_db_session, KnowledgeFile) if file.entry_type == "projection_tombstone"
    )
    assert set(due) == {101, tombstone.id}
