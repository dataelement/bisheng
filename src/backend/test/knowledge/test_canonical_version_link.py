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


async def test_ordinary_file_can_link_into_distributed_manager_document(enable_switch, async_db_session, monkeypatch):
    seeded = await seed_managers(async_db_session)
    # 给目标 manager 文档挂一个 share 分发入口，并将 201 设为普通单版本独立文件
    async_db_session.add(
        KnowledgeFile(
            id=200,
            tenant_id=1,
            knowledge_id=2,
            file_name="target.doc",
            status=2,
            md5="target",
            reference_document_id=seeded.target,
            entry_type="share",
            entry_status="active",
            projection_status="ready",
            desired_content_generation=1,
            applied_content_generation=1,
        )
    )
    ordinary_doc = KnowledgeDocument(tenant_id=1, knowledge_id=1, lifecycle_status="active")
    async_db_session.add(ordinary_doc)
    await async_db_session.flush()
    ordinary_file = KnowledgeFile(
        id=201,
        tenant_id=1,
        knowledge_id=1,
        file_name="ordinary_v2.doc",
        status=2,
        md5="ordinary-md5",
        similar_status=1,
    )
    async_db_session.add(ordinary_file)
    await async_db_session.flush()
    ordinary_ver = KnowledgeDocumentVersion(
        document_id=ordinary_doc.id,
        knowledge_file_id=201,
        version_no=1,
        is_primary=True,
    )
    async_db_session.add(ordinary_ver)
    await async_db_session.flush()
    ordinary_doc.primary_version_id = ordinary_ver.id
    async_db_session.add(ordinary_doc)
    await async_db_session.commit()

    svc = service(async_db_session, monkeypatch)
    result = await svc.link_file_to_document(201, seeded.target)
    assert result.document_id == seeded.target
    assert result.new_version_no == 2

    target_doc = await svc.doc_repo.find_by_id(seeded.target)
    assert target_doc is not None and target_doc.content_generation == 2
    assert await svc.doc_repo.find_by_id(ordinary_doc.id) is None

    new_manager = await svc.knowledge_file_repo.find_by_id(201)
    old_manager = await svc.knowledge_file_repo.find_by_id(100)
    share_entry = await svc.knowledge_file_repo.find_by_id(200)
    assert new_manager is not None and new_manager.entry_type == "manager"
    assert new_manager.reference_document_id == seeded.target
    assert old_manager is not None and old_manager.entry_type is None and old_manager.reference_document_id is None
    assert share_entry is not None and share_entry.file_name == "ordinary_v2.doc"
    assert share_entry.desired_content_generation == 2


async def test_distributed_manager_can_merge_ordinary_source_document(enable_switch, async_db_session, monkeypatch):
    seeded = await seed_managers(async_db_session)
    async_db_session.add(
        KnowledgeFile(
            id=200,
            tenant_id=1,
            knowledge_id=2,
            file_name="target.doc",
            status=2,
            md5="target",
            reference_document_id=seeded.target,
            entry_type="share",
            entry_status="active",
            projection_status="ready",
            desired_content_generation=1,
            applied_content_generation=1,
        )
    )
    ordinary_doc = KnowledgeDocument(tenant_id=1, knowledge_id=1, lifecycle_status="active")
    async_db_session.add(ordinary_doc)
    await async_db_session.flush()
    async_db_session.add(
        KnowledgeFile(
            id=202,
            tenant_id=1,
            knowledge_id=1,
            file_name="ordinary_merge.doc",
            status=2,
            md5="ordinary-merge-md5",
        )
    )
    await async_db_session.flush()
    ordinary_ver = KnowledgeDocumentVersion(
        document_id=ordinary_doc.id,
        knowledge_file_id=202,
        version_no=1,
        is_primary=True,
    )
    async_db_session.add(ordinary_ver)
    await async_db_session.flush()
    ordinary_doc.primary_version_id = ordinary_ver.id
    async_db_session.add(ordinary_doc)
    await async_db_session.commit()

    svc = service(async_db_session, monkeypatch)
    result = await svc.merge_source_document_into_current(100, ordinary_doc.id, force=True)
    assert result.document_id == seeded.target
    assert result.new_version_no == 2

    new_manager = await svc.knowledge_file_repo.find_by_id(202)
    old_manager = await svc.knowledge_file_repo.find_by_id(100)
    assert new_manager is not None and new_manager.entry_type == "manager"
    assert old_manager is not None and old_manager.entry_type is None


async def test_ordinary_link_into_manager_requires_edit_permission(enable_switch, async_db_session, monkeypatch):
    from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError

    seeded = await seed_managers(async_db_session)
    async_db_session.add(
        KnowledgeFile(id=203, tenant_id=1, knowledge_id=1, file_name="ordinary_no_perm.doc", status=2, md5="np")
    )
    await async_db_session.commit()

    svc = service(async_db_session, monkeypatch, denied_file=100)
    with pytest.raises(SpacePermissionDeniedError):
        await svc.link_file_to_document(203, seeded.target)


async def test_share_entry_cannot_link_into_manager_document(enable_switch, async_db_session, monkeypatch):
    seeded = await seed_managers(async_db_session)
    async_db_session.add(
        KnowledgeFile(
            id=204,
            tenant_id=1,
            knowledge_id=1,
            file_name="shared_ref.doc",
            status=2,
            md5="shared-ref",
            reference_document_id=999,
            entry_type="share",
            entry_status="active",
        )
    )
    await async_db_session.commit()

    svc = service(async_db_session, monkeypatch)
    with pytest.raises(KnowledgeDocumentEntryConflictError):
        await svc.link_file_to_document(204, seeded.target)


async def test_single_version_manager_pair_can_associate_without_publish_entries(async_db_session, monkeypatch):
    from bisheng.knowledge.domain.models.knowledge_file_similarity_candidate import KnowledgeFileSimilarityCandidate
    from bisheng.knowledge.domain.services.knowledge_similarity_entry_service import KnowledgeSimilarityEntryService

    seeded = await seed_managers(async_db_session)
    svc = service(async_db_session, monkeypatch)
    entry_svc = KnowledgeSimilarityEntryService(svc)
    source_ctx = await entry_svc.resolve(await svc.knowledge_file_repo.find_by_id(101))
    target_ctx = await entry_svc.resolve(await svc.knowledge_file_repo.find_by_id(100))
    assert source_ctx is not None and target_ctx is not None

    source_file = await svc.knowledge_file_repo.find_by_id(101)
    source_file.user_metadata = {
        "_similarity_snapshot": {
            "source": list(source_ctx.signature),
            "targets": {"100": list(target_ctx.signature)},
        }
    }
    async_db_session.add(source_file)
    await async_db_session.commit()

    row = KnowledgeFileSimilarityCandidate(
        tenant_id=1,
        knowledge_id=1,
        source_file_id=101,
        candidate_file_id=100,
        candidate_document_id=seeded.target,
        similarity=0.95,
        refined_similarity=0.85,
        sort_order=0,
    )
    entries = await entry_svc.cached(101, [row], limit=3, check_permissions=False)
    assert len(entries) == 1
    assert entries[0].can_associate is True


async def test_manager_pair_with_publish_entry_cannot_associate(async_db_session, monkeypatch):
    from bisheng.knowledge.domain.models.knowledge_file_similarity_candidate import KnowledgeFileSimilarityCandidate
    from bisheng.knowledge.domain.services.knowledge_similarity_entry_service import KnowledgeSimilarityEntryService

    seeded = await seed_managers(async_db_session)
    async_db_session.add(
        KnowledgeFile(
            id=205,
            tenant_id=1,
            knowledge_id=2,
            file_name="published_copy.doc",
            status=2,
            md5="pub-copy",
            reference_document_id=seeded.source,
            entry_type="publish",
            entry_status="active",
            projection_status="ready",
            desired_content_generation=14,
            applied_content_generation=14,
            desired_entry_generation=1,
            applied_entry_generation=1,
        )
    )
    await async_db_session.commit()

    svc = service(async_db_session, monkeypatch)
    entry_svc = KnowledgeSimilarityEntryService(svc)
    source_ctx = await entry_svc.resolve(await svc.knowledge_file_repo.find_by_id(101))
    target_ctx = await entry_svc.resolve(await svc.knowledge_file_repo.find_by_id(100))
    assert source_ctx is not None and target_ctx is not None

    source_file = await svc.knowledge_file_repo.find_by_id(101)
    source_file.user_metadata = {
        "_similarity_snapshot": {
            "source": list(source_ctx.signature),
            "targets": {"100": list(target_ctx.signature)},
        }
    }
    async_db_session.add(source_file)
    await async_db_session.commit()

    row = KnowledgeFileSimilarityCandidate(
        tenant_id=1,
        knowledge_id=1,
        source_file_id=101,
        candidate_file_id=100,
        candidate_document_id=seeded.target,
        similarity=0.95,
        refined_similarity=0.85,
        sort_order=0,
    )
    entries = await entry_svc.cached(101, [row], limit=3, check_permissions=False)
    assert len(entries) == 1
    assert entries[0].can_associate is False


async def test_undistributed_manager_can_link_into_distributed_manager_document(
    enable_switch, async_db_session, monkeypatch
):
    from sqlalchemy import select as sa_select

    seeded = await seed_managers(async_db_session)
    # 目标 manager(100, doc=seeded.target) 已挂有 publish 分发入口(210)，源 manager(101, doc=seeded.source) 为独立单版本
    async_db_session.add(
        KnowledgeFile(
            id=210,
            tenant_id=1,
            knowledge_id=2,
            file_name="target_publish.doc",
            status=2,
            md5=None,
            reference_document_id=seeded.target,
            entry_type="publish",
            entry_status="active",
            projection_status="ready",
            desired_content_generation=14,
            applied_content_generation=14,
            desired_entry_generation=1,
            applied_entry_generation=1,
        )
    )
    await async_db_session.commit()

    svc = service(async_db_session, monkeypatch)
    result = await svc.link_file_to_document(101, seeded.target)
    assert result.document_id == seeded.target
    assert result.new_version_no == 2

    old_source_doc = await svc.doc_repo.find_by_id(seeded.source)
    assert old_source_doc is not None and old_source_doc.lifecycle_status == "invalid"
    tombstones = (
        await async_db_session.execute(
            sa_select(KnowledgeFile).where(
                KnowledgeFile.reference_document_id == seeded.source,
                KnowledgeFile.entry_type == "projection_tombstone",
            )
        )
    ).scalars().all()
    assert len(tombstones) == 1
    assert tombstones[0].entry_status == "deleting"
    new_manager = await svc.knowledge_file_repo.find_by_id(101)
    assert new_manager is not None and new_manager.reference_document_id == seeded.target


async def test_distributed_manager_can_merge_undistributed_manager_document(
    enable_switch, async_db_session, monkeypatch
):
    from bisheng.knowledge.domain.services.knowledge_similarity_entry_service import KnowledgeSimilarityEntryService

    seeded = await seed_managers(async_db_session)
    async_db_session.add(
        KnowledgeFile(
            id=211,
            tenant_id=1,
            knowledge_id=2,
            file_name="target_publish.doc",
            status=2,
            md5=None,
            reference_document_id=seeded.target,
            entry_type="publish",
            entry_status="active",
            projection_status="ready",
            desired_content_generation=14,
            applied_content_generation=14,
            desired_entry_generation=1,
            applied_entry_generation=1,
        )
    )
    await async_db_session.commit()

    svc = service(async_db_session, monkeypatch)
    entry_svc = KnowledgeSimilarityEntryService(svc)
    source_ctx = await entry_svc.resolve(await svc.knowledge_file_repo.find_by_id(101))
    target_ctx = await entry_svc.resolve(await svc.knowledge_file_repo.find_by_id(100))
    assert source_ctx is not None and target_ctx is not None
    assert await entry_svc._can_associate_pair(source_ctx, target_ctx) is True
    assert await entry_svc._can_associate_pair(target_ctx, source_ctx) is True

    result = await svc.merge_source_document_into_current(100, seeded.source, force=True)
    assert result.document_id == seeded.target
    assert result.new_version_no == 2

    new_manager = await svc.knowledge_file_repo.find_by_id(101)
    old_manager = await svc.knowledge_file_repo.find_by_id(100)
    assert new_manager is not None and new_manager.entry_type == "manager"
    assert new_manager.reference_document_id == seeded.target
    assert old_manager is not None and old_manager.entry_type is None
