"""Legacy overwrite is a live SPACE file action, not a lossy ordinary retry."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, KnowledgeProcessingConflictError
from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
from bisheng.core.storage.minio import minio_manager
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from test.knowledge_unification import test_kn_upload as native

store, tenant, business, admission = native.store, native.tenant, native.business, native.admission
processing, application, files, legacy, upload = (
    native.processing,
    native.application,
    native.files,
    native.legacy,
    native.upload,
)


@pytest.fixture
async def retry(upload, monkeypatch):
    context = upload.context
    upload.service._require_read_permission = AsyncMock()
    upload.service._require_resource_action = AsyncMock()
    storage = SimpleNamespace(tmp_bucket="temporary", bucket="saved", copy_object=AsyncMock())
    monkeypatch.setattr(minio_manager, "get_minio_storage", AsyncMock(return_value=storage))

    def build():
        from bisheng.knowledge.application import legacy_retry

        monkeypatch.setattr(
            legacy_retry,
            "batch_check_business_actions",
            AsyncMock(
                side_effect=lambda identity, **kwargs: {str(i): frozenset({"rename"}) for i in kwargs["resource_ids"]}
            ),
        )
        monkeypatch.setattr(legacy_retry, "require_business_action", AsyncMock())
        return legacy_retry.LegacyRetryApplication(session_factory=context.sessions)

    upload.service.legacy_retry_factory = build
    async with context.sessions() as session:
        row = await session.get(KnowledgeFile, 81)
        row.file_level_path = ""
        row.similar_status, row.simhash = 1, "old-content"
        await session.commit()
        raw = row.model_dump()
    raw.update(
        object_name="tmp/81.txt", status=3, remark=json.dumps({"new_name": "replacement.txt"}), file_level_path=""
    )
    return SimpleNamespace(upload=upload, storage=storage, raw=raw)


async def run(context, **changes):
    return await context.upload.service.retry_space_files(40, {"file_objs": [{**context.raw, **changes}]})


async def test_file_rename_authority_can_overwrite_without_root_visible(retry):
    retry.upload.service._require_read_permission.side_effect = SpacePermissionDeniedError()
    await run(retry)
    async with retry.upload.context.sessions() as session:
        row = await session.get(KnowledgeFile, 81)
        assert (row.file_name, row.status, row.object_name) == ("replacement.txt", 5, "original/81.txt")
        assert row.split_rule == retry.raw["split_rule"] and row.simhash is None and row.similar_status == 0
    retry.upload.legacy.publish.assert_called_once()
    retry.storage.copy_object.assert_awaited_once()


async def test_overwrite_cannot_change_the_actual_parent_path(retry):
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await run(retry, file_level_path="/999")
    retry.storage.copy_object.assert_not_awaited()
    retry.upload.legacy.publish.assert_not_called()
    async with retry.upload.context.sessions() as session:
        assert (await session.get(KnowledgeFile, 81)).file_level_path == ""


async def test_overwrite_refuses_processing_before_copy_or_dispatch(retry):
    async with retry.upload.context.sessions() as session:
        row = await session.get(KnowledgeFile, 81)
        row.status = 1
        await session.commit()
    with pytest.raises(KnowledgeProcessingConflictError):
        await run(retry)
    retry.storage.copy_object.assert_not_awaited()
    retry.upload.legacy.publish.assert_not_called()
