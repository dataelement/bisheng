"""SPACE upload consumes actual saved rules before V1 registration/dispatch.

The original process_one_file, adapter and native SQL execute. Storage and
permission/queue transports are isolated; no default rule is faked by the test.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlmodel import select

from bisheng.common.errcode.knowledge import KnowledgeProcessingConflictError
from bisheng.knowledge.application.file_processing_adapter import system_processing_defaults
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.services import knowledge_space_service as module
from bisheng.worker.knowledge import scheduler
from test.knowledge_unification import test_legacy_file_processing_callers as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
admission = fixtures.admission
processing = fixtures.processing
application = fixtures.application
files = fixtures.files
legacy = fixtures.legacy


@pytest.fixture
async def upload(legacy, monkeypatch):
    context = legacy.files.context
    monkeypatch.setattr(module, "KnowledgeService", legacy.cls)
    monkeypatch.setattr(module, "get_async_db_session", context.sessions)
    monkeypatch.setattr(module, "get_minio_storage_sync", lambda: legacy.storage)
    service = module.KnowledgeSpaceService(None, context.user)
    service._require_action = AsyncMock()
    service._initialize_child_resource_permissions = AsyncMock()
    service.update_folder_update_time = AsyncMock()
    monkeypatch.setattr(module.SpaceFileDao, "get_user_total_file_size", AsyncMock(return_value=0))
    monkeypatch.setattr(module.QuotaService, "get_knowledge_space_upload_limit_bytes", AsyncMock(return_value=None))
    monkeypatch.setattr(module.QuotaService, "get_tenant_storage_remaining_bytes", AsyncMock(return_value=None))
    monkeypatch.setattr(module.KnowledgeDao, "async_update_knowledge_update_time_by_id", AsyncMock())
    publish = Mock()
    monkeypatch.setattr(scheduler, "enqueue_or_dispatch", publish)
    preview_rules = []

    def cache_key(space_id, path, rules):
        preview_rules.append((space_id, path, rules))
        return "actual-rule-cache-key"

    monkeypatch.setattr(service, "preview_cache_key_for_split_rule", cache_key)
    return SimpleNamespace(
        service=service, context=context, legacy=legacy, publish=publish, preview_rules=preview_rules
    )


@pytest.mark.parametrize("path,kind", [("opaque-document", "document"), ("opaque-table", "table")])
async def test_upload_persists_actual_space_default_and_version_before_dispatch(upload, path, kind):
    rows = await upload.service.add_file(40, [path])
    assert len(rows) == 1
    accepted = rows[0]
    actual = json.loads(accepted.split_rule)
    assert "_effective_processing" in actual
    snapshot = actual["_effective_processing"]
    assert snapshot["file_kind"] == kind and snapshot["space_config_version"] == 3
    assert "file" not in snapshot["supplied_fields_by_layer"]
    if kind == "document":
        assert actual["chunk_size"] == 800 and actual["force_ocr"] == 0
    else:
        assert actual["excel_rule"]["slice_length"] == 44
    assert upload.preview_rules == [(40, path, actual)]
    upload.service._require_action.assert_awaited_once_with("knowledge_space", 40, "upload_file")
    upload.publish.assert_called_once_with(
        user_id=7,
        file_id=accepted.id,
        file_name=accepted.file_name,
        preview_cache_key="actual-rule-cache-key",
        callback_url=None,
    )
    async with upload.context.sessions() as session:
        file = await session.get(KnowledgeFile, accepted.id)
        assert json.loads(file.split_rule) == actual
        version = (
            await session.exec(
                select(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.knowledge_file_id == file.id)
            )
        ).one()
        document = await session.get(KnowledgeDocument, version.document_id)
        assert (version.version_no, version.is_primary, document.primary_version_id) == (1, True, version.id)
        assert (document.knowledge_id, document.level, document.file_level_path) == (40, 0, "")
        assert (await session.get(KnowledgeDocument, 80)).primary_version_id == 181
        assert (await session.get(KnowledgeDocumentVersion, 182)).knowledge_file_id == 82
        root = await session.get(Knowledge, 40)
        root.processing_defaults = system_processing_defaults(40).model_dump(mode="json")
        root.processing_config_version += 1
        await session.commit()
    async with upload.context.sessions() as session:
        assert json.loads((await session.get(KnowledgeFile, accepted.id)).split_rule) == actual


async def test_upload_without_space_defaults_captures_actual_system_defaults(upload):
    async with upload.context.sessions() as session:
        root = await session.get(Knowledge, 40)
        root.processing_defaults, root.processing_config_version = None, 0
        await session.commit()
    accepted = (await upload.service.add_file(40, ["opaque-document"]))[0]
    actual = json.loads(accepted.split_rule)
    assert actual["_effective_processing"]["effective_rule"] == system_processing_defaults(40).document.model_dump()
    assert actual["_effective_processing"]["space_config_version"] == 0
    assert actual["_effective_processing"]["supplied_fields_by_layer"]["batch"] == []


async def test_duplicate_does_not_register_another_version_or_dispatch(upload):
    first = (await upload.service.add_file(40, ["opaque-document"]))[0]
    upload.publish.reset_mock()
    again = (await upload.service.add_file(40, ["opaque-document"]))[0]
    assert again.id == first.id and again.status == 3
    upload.publish.assert_not_called()
    async with upload.context.sessions() as session:
        versions = (
            await session.exec(
                select(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.knowledge_file_id == first.id)
            )
        ).all()
        assert len(versions) == 1 and versions[0].version_no == 1


async def test_active_rebuild_refuses_upload_before_storage_or_dispatch(upload):
    async with upload.context.sessions() as session:
        root = await session.get(Knowledge, 40)
        root.model_transition = {"operation_id": "active-rebuild", "state": "rebuilding"}
        await session.commit()
    upload.legacy.storage.reset_mock()
    with pytest.raises(KnowledgeProcessingConflictError):
        await upload.service.add_file(40, ["opaque-document"])
    upload.publish.assert_not_called()
    upload.legacy.storage.put_object_sync.assert_not_called()
