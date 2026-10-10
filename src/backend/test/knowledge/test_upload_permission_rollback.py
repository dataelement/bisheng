"""Root uploads and partial-batch compensation without external middleware."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.knowledge.domain.services import knowledge_space_service as module
from bisheng.knowledge.domain.services.knowledge_permission_service import F048KnowledgeFilePermissionAdapter
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from test.knowledge.test_knowledge_space_service import _make_file, _make_login_user, _make_space


@pytest.fixture
def upload(monkeypatch):
    service = module.KnowledgeSpaceService(None, _make_login_user())
    space = _make_space(space_id=348)
    space.tenant_id = 1
    files = [_make_file(file_id=i, knowledge_id=348) for i in (347, 348, 349)]
    for row in files:
        row.tenant_id = 1
        row.user_id = 7
        row.file_size = 1
        row.object_name = f"original/{row.id}.txt"
    business = {row.id: row for row in files}
    permissions = {}
    events = []

    async def create(**kwargs):
        target = kwargs["target"]
        permissions[int(target.resource_id)] = target

    async def rollback(**kwargs):
        file_id = int(kwargs["target"].resource_id)
        events.append(("permission", file_id))
        permissions.pop(file_id, None)

    permission = SimpleNamespace(
        authorize_created=AsyncMock(side_effect=create), rollback_created=AsyncMock(side_effect=rollback)
    )
    adapter = F048KnowledgeFilePermissionAdapter(loader=None, permission=permission)
    monkeypatch.setattr(service, "_resource_adapter", AsyncMock(return_value=adapter))
    monkeypatch.setattr(
        service, "_permission_actor", AsyncMock(return_value=PermissionActor(user_id=7, current_tenant_id=1))
    )
    monkeypatch.setattr(service, "_require_action", AsyncMock())
    monkeypatch.setattr(module.KnowledgeDao, "aquery_by_id", AsyncMock(return_value=space))
    monkeypatch.setattr(module.KnowledgeDao, "async_update_knowledge_update_time_by_id", AsyncMock())
    monkeypatch.setattr(module.SpaceFileDao, "get_user_total_file_size", AsyncMock(return_value=0))
    monkeypatch.setattr(module.QuotaService, "get_knowledge_space_upload_limit_bytes", AsyncMock(return_value=None))
    monkeypatch.setattr(module.QuotaService, "get_tenant_storage_remaining_bytes", AsyncMock(return_value=None))
    monkeypatch.setattr(module.KnowledgeService, "process_one_file", MagicMock(side_effect=files))
    monkeypatch.setattr(module.KnowledgeFileDao, "update", lambda row: row)
    monkeypatch.setattr(module.KnowledgeFileDao, "query_by_id", AsyncMock(side_effect=business.get))

    async def delete(ids):
        for file_id in ids:
            events.append(("business", file_id))
            business.pop(file_id, None)

    monkeypatch.setattr(module.KnowledgeFileDao, "adelete_batch", AsyncMock(side_effect=delete))
    storage = MagicMock()
    monkeypatch.setattr(module, "get_minio_storage_sync", lambda: storage)
    from bisheng.worker.knowledge import scheduler

    dispatch = MagicMock()
    monkeypatch.setattr(scheduler, "enqueue_or_dispatch", dispatch)
    return SimpleNamespace(
        service=service,
        files=files,
        business=business,
        permissions=permissions,
        permission=permission,
        events=events,
        storage=storage,
        dispatch=dispatch,
    )


def _use_session(monkeypatch, session):
    @asynccontextmanager
    async def factory():
        yield session

    monkeypatch.setattr(module, "get_async_db_session", factory)


async def test_root_upload_with_matching_space_file_id(upload, monkeypatch, async_db_session):
    _use_session(monkeypatch, async_db_session)
    result = await upload.service.add_file(348, ["a", "b", "c"], parent_id=None)
    assert [row.id for row in result] == [347, 348, 349]
    assert upload.permissions[348].parent_type == "knowledge_space"
    assert upload.permissions[348].parent_id == "348"
    assert upload.dispatch.call_count == 3
    upload.permission.rollback_created.assert_not_awaited()


async def test_mid_batch_failure_cleans_initialized_and_uninitialized_files(upload, monkeypatch, async_db_session):
    from sqlmodel import select

    from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
        KnowledgeDocumentRepositoryImpl,
    )
    from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
        KnowledgeDocumentVersionRepositoryImpl,
    )

    _use_session(monkeypatch, async_db_session)
    upload.service.doc_repo = KnowledgeDocumentRepositoryImpl(async_db_session)
    upload.service.version_repo = KnowledgeDocumentVersionRepositoryImpl(async_db_session)
    create = upload.permission.authorize_created.side_effect

    async def fail_second(**kwargs):
        if kwargs["target"].resource_id == "348":
            raise RuntimeError("injected upload failure")
        await create(**kwargs)

    upload.permission.authorize_created.side_effect = fail_second
    with pytest.raises(RuntimeError, match="injected upload failure"):
        await upload.service.add_file(348, ["a", "b", "c"])
    assert not upload.business
    assert not upload.permissions
    for model in (module.KnowledgeDocument, module.KnowledgeDocumentVersion):
        assert not (await async_db_session.execute(select(model))).scalars().all()
    assert upload.storage.remove_object_sync.call_count == 3
    assert upload.permission.rollback_created.await_count == 3
    upload.dispatch.assert_not_called()
    for file_id in (347, 348, 349):
        assert upload.events.index(("permission", file_id)) < upload.events.index(("business", file_id))


async def test_cleanup_failure_retains_affected_business_row_and_continues(upload):
    rollback = upload.permission.rollback_created.side_effect

    async def fail_second(**kwargs):
        if kwargs["target"].resource_id == "348":
            raise RuntimeError("permission service unavailable")
        await rollback(**kwargs)

    upload.permission.rollback_created.side_effect = fail_second
    with pytest.raises(ExceptionGroup):
        await upload.service._rollback_uploaded_files(upload.files, parent_type="knowledge_space", parent_id=348)
    assert list(upload.business) == [348]
    assert upload.storage.remove_object_sync.call_count == 2
