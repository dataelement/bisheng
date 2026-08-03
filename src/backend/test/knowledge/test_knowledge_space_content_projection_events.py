"""Lifecycle events that must refresh knowledge-space content snapshots."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.common.errcode.knowledge_space import SpaceFolderDuplicateError
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile
from bisheng.knowledge.domain.services.knowledge_space_service import (
    KnowledgeSpaceService,
)


def _service() -> KnowledgeSpaceService:
    return KnowledgeSpaceService(
        MagicMock(),
        SimpleNamespace(user_id=7, user_name="tester", tenant_id=1),
    )


@pytest.mark.asyncio
async def test_rename_folder_enqueues_all_descendant_file_ids_after_update():
    service = _service()
    service._require_permission_id = AsyncMock()
    service._check_name_sensitive_words = MagicMock()
    folder = KnowledgeFile(
        id=10,
        knowledge_id=3,
        file_name="旧目录",
        file_type=FileType.DIR.value,
        file_level_path="/2",
    )
    descendants = [
        SimpleNamespace(id=11, file_type=FileType.FILE.value),
        SimpleNamespace(id=12, file_type=FileType.DIR.value),
        SimpleNamespace(id=13, file_type=FileType.FILE.value),
    ]

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id",
            new=AsyncMock(return_value=folder),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.SpaceFileDao.count_folder_by_name",
            new=AsyncMock(return_value=0),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.async_update",
            new=AsyncMock(side_effect=lambda record: record),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "KnowledgeDao.async_update_knowledge_update_time_by_id",
            new=AsyncMock(),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.SpaceFileDao.get_children_by_prefix",
            new=AsyncMock(return_value=descendants),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "KnowledgeSpaceContentStat.enqueue_file_stat_async",
            new=AsyncMock(return_value=True),
        ) as enqueue_projection,
    ):
        updated = await service.rename_folder(10, "新目录")

    assert updated.file_name == "新目录"
    enqueue_projection.assert_awaited_once_with([11, 13])


@pytest.mark.asyncio
async def test_failed_folder_rename_does_not_enqueue_projection():
    service = _service()
    service._require_permission_id = AsyncMock()
    service._check_name_sensitive_words = MagicMock()
    folder = KnowledgeFile(
        id=10,
        knowledge_id=3,
        file_name="旧目录",
        file_type=FileType.DIR.value,
        file_level_path="/2",
    )

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id",
            new=AsyncMock(return_value=folder),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.SpaceFileDao.count_folder_by_name",
            new=AsyncMock(return_value=1),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "KnowledgeSpaceContentStat.enqueue_file_stat_async",
            new=AsyncMock(return_value=True),
        ) as enqueue_projection,
    ):
        with pytest.raises(SpaceFolderDuplicateError):
            await service.rename_folder(10, "重复目录")

    enqueue_projection.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_file_tags_enqueues_projection_after_tag_writes():
    service = _service()
    file_record = SimpleNamespace(id=21, file_name="制度.pdf")
    service._get_file_for_action = AsyncMock(return_value=file_record)
    service._load_file_tags_batch = AsyncMock(
        side_effect=[{21: [{"name": "旧标签"}]}, {21: [{"name": "新标签"}]}]
    )
    service._require_document_content_manager = AsyncMock(return_value=None)
    service._require_permission_id = AsyncMock()
    service._partition_file_tag_ids_for_update = AsyncMock(return_value=([1], []))
    service._promote_review_tags_existing_in_libraries = AsyncMock(
        return_value=([1], [])
    )
    service._notify_favorite_source_changed = AsyncMock()

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "TagDao.aupdate_resource_tags",
            new=AsyncMock(),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "ReviewTagDao.aupdate_resource_tags",
            new=AsyncMock(),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "KnowledgeDao.async_update_knowledge_update_time_by_id",
            new=AsyncMock(),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "KnowledgeSpaceContentStat.enqueue_file_stat_async",
            new=AsyncMock(return_value=True),
        ) as enqueue_projection,
    ):
        await service.update_file_tags(3, 21, [1], [])

    enqueue_projection.assert_awaited_once_with([21])


@pytest.mark.asyncio
async def test_batch_add_file_tags_enqueues_all_actual_files_after_writes():
    service = _service()
    files = [
        SimpleNamespace(id=21, file_name="一.pdf"),
        SimpleNamespace(id=22, file_name="二.pdf"),
    ]
    service._require_read_permission = AsyncMock()
    service._get_space_files_or_raise = AsyncMock(return_value=files)
    service._load_file_tags_batch = AsyncMock(return_value={})
    service._partition_file_tag_ids_for_update = AsyncMock(return_value=([1], []))
    service._promote_review_tags_existing_in_libraries = AsyncMock(
        return_value=([1], [])
    )
    service._require_document_content_manager = AsyncMock(return_value=None)
    service._require_permission_id = AsyncMock()
    service._notify_favorite_source_changed = AsyncMock()

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "TagDao.add_tags",
            new=AsyncMock(),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "KnowledgeDao.async_update_knowledge_update_time_by_id",
            new=AsyncMock(),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "KnowledgeSpaceContentStat.enqueue_file_stat_async",
            new=AsyncMock(return_value=True),
        ) as enqueue_projection,
    ):
        await service.batch_add_file_tags(3, [21, 22, 999], [1], [])

    enqueue_projection.assert_awaited_once_with([21, 22])
