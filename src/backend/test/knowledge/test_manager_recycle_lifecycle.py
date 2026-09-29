"""管理入口回收、还原与清空的数据库集成回归。"""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlmodel import select

from bisheng.common.models.config import Config
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_recycle_item import KnowledgeRecycleItem
from bisheng.knowledge.domain.schemas.knowledge_recycle import RecyclePurgeRequest, RecycleRestoreRequest
from bisheng.knowledge.domain.services.knowledge_document_distribution_service import ShareKnowledgeDocumentCommand
from bisheng.knowledge.domain.services.knowledge_document_recycle_service import KnowledgeDocumentRecycleService
from bisheng.knowledge.domain.services.knowledge_recycle_service import KnowledgeRecycleService
from test.knowledge.test_document_projection_batch_worker import worker as _worker_fixture
from test.knowledge.test_knowledge_document_distribution_delete import _seed_manager, _service

worker = _worker_fixture


@pytest.fixture(autouse=True)
def tenant_scope(tenant_context):
    tenant_context(7)


@pytest.fixture
async def recycled(async_db_session, monkeypatch):
    session = async_db_session
    await _seed_manager(session)
    manager = await session.get(KnowledgeFile, 100)
    manager.file_level_path = ""
    manager.level = 0
    session.add(manager)
    session.add(Config(key="knowledge_recycle_bin.retention_days", value="14"))
    session.add(
        KnowledgeFile(
            id=105, tenant_id=7, knowledge_id=10, file_name="old.pdf", object_name="tenant/7/old.pdf", status=2
        )
    )
    session.add(KnowledgeDocumentVersion(id=502, document_id=91, knowledge_file_id=105, version_no=2, is_primary=False))
    await session.commit()
    service = _service(session)
    share = await service.share_approved(
        ShareKnowledgeDocumentCommand(
            tenant_id=7,
            approval_instance_id=8001,
            document_id=91,
            source_entry_id=100,
            target_space_id=30,
        )
    )
    result = await service.delete_manager(
        tenant_id=7, document_id=91, manager_file_id=100, actor_id=11, actor_name="管理员甲"
    )
    assert result.action == "recycle"

    @asynccontextmanager
    async def use_session():
        try:
            yield session
        except Exception:
            await session.rollback()
            raise

    module = "bisheng.knowledge.domain.services.knowledge_recycle_service"
    monkeypatch.setattr(KnowledgeRecycleService, "_enqueue_document_projection", lambda *_args: None)

    async def knowledge_by_id(fid):
        return await session.get(Knowledge, fid)

    async def file_by_id(fid):
        return await session.get(KnowledgeFile, fid)

    monkeypatch.setattr(f"{module}.get_async_db_session", use_session)
    monkeypatch.setattr(f"{module}.KnowledgeDao.aquery_by_id", AsyncMock(side_effect=knowledge_by_id))
    monkeypatch.setattr(f"{module}.KnowledgeFileDao.query_by_id", AsyncMock(side_effect=file_by_id))
    monkeypatch.setattr(f"{module}.KnowledgeSpaceContentStat.enqueue_file_stat_async", AsyncMock())
    monkeypatch.setattr("bisheng.knowledge.rag.shared_space_storage.aresolve_space_shared_routing", AsyncMock())
    api = KnowledgeRecycleService(SimpleNamespace(user_id=11, user_name="管理员甲", tenant_id=7, is_admin=lambda: True))
    item = (
        (await session.execute(select(KnowledgeRecycleItem).where(KnowledgeRecycleItem.is_list_entry.is_(True))))
        .scalars()
        .one()
    )
    return session, api, item, share.share_entry_id, use_session


async def test_recycle_keeps_versions_and_one_visible_item(recycled):
    session, _, item, share_id, _ = recycled
    rows = (await session.execute(select(KnowledgeRecycleItem))).scalars().all()
    assert {row.file_id for row in rows} == {100, 105, share_id}
    assert sum(row.is_list_entry for row in rows) == 1
    assert item.deleted_by == 11 and item.deleted_by_name == "管理员甲"
    assert item.expire_at - item.deleted_at == timedelta(days=14)
    assert set(item.version_file_ids) == {100, 105}
    document = await session.get(KnowledgeDocument, 91)
    assert document.lifecycle_status == "recycled" and document.primary_version_id == 501
    for fid in (100, 105, share_id):
        assert (await session.get(KnowledgeFile, fid)).deleted_at is not None
    assert (await session.get(KnowledgeFile, 105)).object_name == "tenant/7/old.pdf"


@pytest.mark.parametrize("target_id", [10, 20])
async def test_public_restore_restores_versions_and_share_at_own_location(recycled, monkeypatch, target_id):
    session, api, item, share_id, _ = recycled
    permissions = AsyncMock()
    monkeypatch.setattr(
        "bisheng.permission.domain.services.permission_service.PermissionService.batch_write_tuples", permissions
    )
    result = await api.restore(
        RecycleRestoreRequest(
            item_ids=[item.id],
            mode="original" if target_id == 10 else "custom",
            target_knowledge_id=target_id,
        )
    )
    assert result == {"restored": 1}
    document = await session.get(KnowledgeDocument, 91)
    assert document.lifecycle_status == "active" and document.knowledge_id == target_id
    for fid in (100, 105):
        file = await session.get(KnowledgeFile, fid)
        assert file.knowledge_id == target_id and file.deleted_at is None
    share = await session.get(KnowledgeFile, share_id)
    assert share.knowledge_id == 30 and share.entry_status == "active" and share.deleted_at is None
    assert share.projection_status == "pending"
    assert not (await session.execute(select(KnowledgeRecycleItem))).scalars().all()
    if target_id == 20:
        operations = permissions.await_args.args[0]
        assert [(op.action, op.user) for op in operations] == [
            ("delete", "knowledge_space:10"),
            ("write", "knowledge_space:20"),
        ]
    with pytest.raises(ValueError, match="已被还原或清理"):
        await KnowledgeDocumentRecycleService(session).purge(item)


@pytest.mark.parametrize("failure", ["share_missing", "cross_tenant", "permission"])
async def test_restore_failure_preserves_recycle_and_versions(recycled, monkeypatch, failure):
    session, _, item, share_id, _ = recycled
    if failure == "share_missing":
        await session.delete(await session.get(Knowledge, 30))
    elif failure == "cross_tenant":
        target = await session.get(Knowledge, 20)
        target.tenant_id = 99
        session.add(target)
    else:
        monkeypatch.setattr(
            "bisheng.permission.domain.services.permission_service.PermissionService.batch_write_tuples",
            AsyncMock(side_effect=RuntimeError("FGA unavailable")),
        )
    await session.commit()
    with pytest.raises((ValueError, RuntimeError)):
        await KnowledgeDocumentRecycleService(session).restore(item, target_knowledge_id=20, target_path="")
    await session.rollback()
    assert (await session.get(KnowledgeDocument, 91)).lifecycle_status == "recycled"
    assert (await session.get(KnowledgeFile, 100)).deleted_at is not None
    assert (await session.get(KnowledgeFile, share_id)).entry_status == "invalid"
    assert len((await session.execute(select(KnowledgeDocumentVersion))).scalars().all()) == 2
    assert len((await session.execute(select(KnowledgeRecycleItem))).scalars().all()) == 3


@pytest.mark.parametrize("expired", [False, True])
async def test_public_purge_and_expiry_only_schedule_final_cleanup(recycled, expired):
    session, api, item, share_id, _ = recycled
    if expired:
        item.expire_at = datetime.now() - timedelta(seconds=1)
        session.add(item)
        await session.commit()
        assert await api.purge_expired_items() == 1
    else:
        assert await api.purge(RecyclePurgeRequest(item_ids=[item.id])) == {"purged": 3}
    assert (await session.get(KnowledgeDocument, 91)).lifecycle_status == "deleting"
    assert (await session.get(KnowledgeFile, 100)).entry_status == "deleting"
    assert (await session.get(KnowledgeFile, share_id)).entry_status == "deleting"
    assert len((await session.execute(select(KnowledgeDocumentVersion))).scalars().all()) == 2
    assert not (await session.execute(select(KnowledgeRecycleItem))).scalars().all()
    with pytest.raises(ValueError, match="已被还原或清理"):
        await KnowledgeDocumentRecycleService(session).restore(item, target_knowledge_id=10, target_path="")


async def test_projection_cleanup_cannot_remove_recycled_permissions_or_content(recycled, worker, monkeypatch):
    session, _, _, share_id, use_session = recycled
    monkeypatch.setattr(worker, "get_async_db_session", use_session)
    delete_permissions = AsyncMock()
    delete_objects = AsyncMock()
    monkeypatch.setattr(worker, "_delete_entry_permissions", delete_permissions)
    monkeypatch.setattr(worker, "_strict_delete_minio_objects", delete_objects)
    await worker._finalize_deleting_entry(await session.get(KnowledgeFile, share_id))
    await worker._finalize_document_delete(await session.get(KnowledgeFile, 100))
    delete_permissions.assert_not_awaited()
    delete_objects.assert_not_awaited()
    assert (await session.get(KnowledgeFile, 100)).object_name == "tenant/7/canonical.pdf"


async def test_restore_conflict_preserves_both_documents_even_when_overwrite_requested(recycled):
    from bisheng.common.errcode.knowledge import KnowledgeRecycleTaskError

    session, api, item, _, _ = recycled
    session.add(KnowledgeFile(id=200, tenant_id=7, knowledge_id=20, file_name="canonical.pdf", object_name="other.pdf"))
    await session.commit()
    with pytest.raises(KnowledgeRecycleTaskError, match="重复文件"):
        await api.restore(
            RecycleRestoreRequest(item_ids=[item.id], mode="custom", target_knowledge_id=20, overwrite_files=True)
        )
    assert (await session.get(KnowledgeFile, 200)).object_name == "other.pdf"
    assert (await session.get(KnowledgeDocument, 91)).lifecycle_status == "recycled"


async def test_deleting_original_space_preserves_recycled_versions(recycled, monkeypatch):
    from bisheng.knowledge.domain.models.knowledge import KnowledgeDao

    session, _, _item, _share_id, use_session = recycled
    monkeypatch.setattr("bisheng.knowledge.domain.models.knowledge.get_async_db_session", use_session)
    await KnowledgeDao.async_delete_knowledge(10, preserve_recycled=True)
    assert await session.get(Knowledge, 10) is None
    assert (await session.get(KnowledgeFile, 100)).object_name == "tenant/7/canonical.pdf"
    assert (await session.get(KnowledgeFile, 105)).object_name == "tenant/7/old.pdf"
    assert len((await session.execute(select(KnowledgeRecycleItem))).scalars().all()) == 3


async def test_final_cleanup_removes_all_versions_only_after_purge(recycled, worker, monkeypatch):
    from unittest.mock import MagicMock

    from bisheng.knowledge.domain.models.knowledge_file_pdf_artifact import KnowledgeFilePdfArtifact

    session, api, item, share_id, use_session = recycled
    connection = await session.connection()
    await connection.run_sync(lambda conn: KnowledgeFilePdfArtifact.__table__.create(conn, checkfirst=True))
    await api.purge(RecyclePurgeRequest(item_ids=[item.id]))
    for fid in (100, share_id):
        entry = await session.get(KnowledgeFile, fid)
        entry.projection_status = "ready"
        entry.projection_lease_owner = "cleanup"
        entry.applied_content_generation = entry.desired_content_generation
        entry.applied_entry_generation = entry.desired_entry_generation
        session.add(entry)
    await session.commit()
    monkeypatch.setattr(worker, "get_async_db_session", use_session)
    delete_objects = AsyncMock()
    monkeypatch.setattr(worker, "_strict_delete_minio_objects", delete_objects)
    monkeypatch.setattr(worker, "_delete_entry_permissions", AsyncMock())
    monkeypatch.setattr("bisheng.api.services.knowledge_imp.delete_vector_files", MagicMock())
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_pdf_artifact_service.get_pdf_artifact_deletion_snapshots",
        AsyncMock(return_value=[]),
    )
    await worker._finalize_document_delete((await session.get(KnowledgeFile, 100)).model_copy())
    assert {file.id for file in delete_objects.await_args.args[0]} == {100, 105}
    assert await session.get(KnowledgeDocument, 91) is None
    assert not (await session.execute(select(KnowledgeDocumentVersion))).scalars().all()
    assert not (await session.execute(select(KnowledgeFile))).scalars().all()


async def test_container_cascade_cannot_delete_managed_history_version(recycled):
    from unittest.mock import MagicMock

    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

    session, _, _, _, _ = recycled
    distribution = _service(session)
    service = KnowledgeSpaceService(request=MagicMock(), login_user=SimpleNamespace(tenant_id=7))
    service.version_repo = distribution.version_repository
    service.doc_repo = distribution.document_repository
    service.document_distribution_service = distribution
    plan = await service._plan_cascade_version_links_on_delete([105])
    assert plan.expanded_file_ids == []
    assert plan.version_ids == [] and plan.document_ids == []


async def test_recycled_share_denies_access_and_removes_search_membership(recycled, worker, monkeypatch):
    from bisheng.knowledge.domain.services.knowledge_document_entry_resolver import (
        KnowledgeDocumentEntryResolutionError,
        KnowledgeDocumentEntryResolver,
    )
    from bisheng.knowledge.domain.services.knowledge_document_projection_service import (
        KnowledgeDocumentProjectionService,
    )

    session, _, _, share_id, use_session = recycled
    distribution = _service(session)
    resolver = KnowledgeDocumentEntryResolver(
        document_repository=distribution.document_repository,
        version_repository=distribution.version_repository,
        file_repository=distribution.file_repository,
        permission_loader=AsyncMock(return_value={"view_file"}),
    )
    with pytest.raises(KnowledgeDocumentEntryResolutionError, match="not active"):
        await resolver.resolve(tenant_id=7, space_id=30, file_id=share_id)
    monkeypatch.setattr(worker, "get_async_db_session", use_session)
    permissions = AsyncMock()
    monkeypatch.setattr(worker, "_delete_entry_permissions", permissions)
    writer = AsyncMock()
    projection = KnowledgeDocumentProjectionService(
        session=session,
        file_repository=distribution.file_repository,
        document_repository=distribution.document_repository,
        version_repository=distribution.version_repository,
        shared_storage_writer=writer,
        deleting_entry_finalizer=worker._finalize_deleting_entry,
    )
    result = await projection.process_entry(tenant_id=7, entry_id=share_id, lease_owner="test-recycle")
    assert result.status == "cleaned"
    writer.delete_content.assert_awaited_once()
    permissions.assert_not_awaited()
    assert await session.get(KnowledgeFile, 100) is not None


def test_space_storage_cleanup_excludes_recycled_files(db_session, monkeypatch):
    from contextlib import contextmanager

    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao

    db_session.add_all(
        [
            KnowledgeFile(id=901, tenant_id=7, knowledge_id=10, file_name="kept.pdf", deleted_at=datetime.now()),
            KnowledgeFile(id=902, tenant_id=7, knowledge_id=10, file_name="active.pdf"),
        ]
    )
    db_session.flush()

    @contextmanager
    def use_sync_session():
        yield db_session

    monkeypatch.setattr("bisheng.knowledge.domain.models.knowledge_file.get_sync_db_session", use_sync_session)
    assert KnowledgeFileDao.count_file_by_knowledge_id(10) == 1
    assert [row[0] for row in KnowledgeFileDao.get_file_simple_by_knowledge_id(10, 1, 100)] == [902]
