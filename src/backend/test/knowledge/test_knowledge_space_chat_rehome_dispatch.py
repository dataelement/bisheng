import asyncio
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


def _service() -> KnowledgeSpaceService:
    return KnowledgeSpaceService(
        request=MagicMock(),
        login_user=SimpleNamespace(user_id=7, user_name="user-7", tenant_id=1),
    )


async def test_batch_delete_normalization_removes_duplicates_and_covered_descendants():
    service = _service()
    rows = [
        SimpleNamespace(id=10, knowledge_id=1, file_level_path=""),
        SimpleNamespace(id=11, knowledge_id=1, file_level_path="/10"),
        SimpleNamespace(id=12, knowledge_id=1, file_level_path="/10/11"),
        SimpleNamespace(id=20, knowledge_id=1, file_level_path="/10/11"),
        SimpleNamespace(id=21, knowledge_id=1, file_level_path=""),
    ]

    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.aget_file_by_ids",
        new_callable=AsyncMock,
        return_value=rows,
    ):
        file_ids, folder_ids = await service._normalize_batch_delete_inputs(
            1,
            [20, 20, 21],
            [10, 11, 12, 10],
        )

    assert file_ids == [21]
    assert folder_ids == [10]


async def test_clear_space_dispatches_after_delete_commit_before_index_recreate():
    service = _service()
    events: list[str] = []
    space = SimpleNamespace(id=1, type=KnowledgeTypeEnum.SPACE.value)
    service._require_action = AsyncMock()
    service._list_space_child_resources = AsyncMock(return_value=[("folder", 10), ("knowledge_file", 20)])
    service._load_resource_permission_records = AsyncMock(return_value=[])
    service._project_resource_deletes = AsyncMock()
    service._dispatch_knowledge_chat_rehome = MagicMock(side_effect=lambda **kwargs: events.append("dispatch"))

    async def fake_to_thread(function, *args):
        return function(*args)

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new_callable=AsyncMock,
            return_value=space,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_delete_knowledge",
            new_callable=AsyncMock,
            side_effect=lambda **kwargs: events.append("delete_commit"),
        ),
        patch.object(
            asyncio,
            "to_thread",
            new=fake_to_thread,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "KnowledgeService.delete_knowledge_file_in_vector",
            side_effect=lambda *args: events.append("vector_delete"),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeService.delete_knowledge_file_in_minio",
            side_effect=lambda *args: events.append("minio_delete"),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeService._init_knowledge_indices_sync",
            side_effect=lambda *args: events.append("index_recreate"),
        ),
    ):
        await service.clear_space(1)

    assert events.index("delete_commit") < events.index("dispatch") < events.index("index_recreate")
    service._dispatch_knowledge_chat_rehome.assert_called_once_with(
        source_space_id=1,
        resources=[("folder", 10), ("knowledge_file", 20)],
        reason="clear_space",
    )


async def test_delete_file_dispatches_only_after_hard_delete_commit():
    service = _service()
    events: list[str] = []
    file_record = SimpleNamespace(
        id=20,
        knowledge_id=1,
        file_level_path="/10",
    )
    service._get_file_for_action = AsyncMock(return_value=file_record)
    service._require_action = AsyncMock()
    service._ensure_space_async_task_tenant_consistency = MagicMock()
    service._cascade_version_links_on_delete = AsyncMock(return_value=[20, 21])
    service._cleanup_resource_tuples = AsyncMock()
    service.update_folder_update_time = AsyncMock()
    service._dispatch_knowledge_chat_rehome = MagicMock(side_effect=lambda **kwargs: events.append("dispatch"))

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(id=1),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.adelete_batch",
            new_callable=AsyncMock,
            side_effect=lambda *args: events.append("hard_delete_commit"),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "KnowledgeDao.async_update_knowledge_update_time_by_id",
            new_callable=AsyncMock,
        ),
    ):
        await service.delete_file(20)

    assert events == ["hard_delete_commit", "dispatch"]
    service._dispatch_knowledge_chat_rehome.assert_called_once_with(
        source_space_id=1,
        resources=[("knowledge_file", 20), ("knowledge_file", 21)],
        reason="delete_file",
    )


def test_cross_space_move_dispatch_is_after_commit_before_other_side_effects():
    source = inspect.getsource(KnowledgeSpaceService.move_items)

    commit_position = source.index("await session.commit()")
    dispatch_position = source.index("self._dispatch_knowledge_chat_rehome(")
    permission_position = source.index("await self._replace_resource_parent_tuple(")

    assert commit_position < dispatch_position < permission_position
    assert "if cross_space:" in source[:dispatch_position]
    assert "direct_move_resources" in source
