"""Batch retry accepts every status classified as abnormal."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from bisheng import worker as worker_module
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

_SERVICE = "bisheng.knowledge.domain.services.knowledge_space_service"


async def test_batch_retry_accepts_timeout_file():
    user = SimpleNamespace(user_id=41, tenant_id=7)
    service = KnowledgeSpaceService(request=None, login_user=user)
    space = SimpleNamespace(id=9, tenant_id=7)
    timeout_file = KnowledgeFile(
        id=17,
        user_id=41,
        tenant_id=7,
        knowledge_id=9,
        file_name="timeout.pdf",
        file_type=FileType.FILE.value,
        file_level_path="",
        status=KnowledgeFileStatus.TIMEOUT.value,
    )
    retry_task = SimpleNamespace(delay=MagicMock())

    with (
        patch.object(worker_module, "retry_knowledge_file_celery", retry_task),
        patch(f"{_SERVICE}.KnowledgeDao.aquery_by_id", new=AsyncMock(return_value=space)),
        patch(f"{_SERVICE}.KnowledgeFileDao.aget_file_by_ids", new=AsyncMock(return_value=[timeout_file])),
        patch(f"{_SERVICE}.KnowledgeFileDao.aupdate_file_status", new=AsyncMock()) as update_status,
        patch(f"{_SERVICE}.KnowledgeDao.async_update_knowledge_update_time_by_id", new=AsyncMock()),
        patch.object(service, "_require_read_permission", new=AsyncMock()),
        patch.object(service, "_require_resource_action", new=AsyncMock()) as require_action,
        patch.object(service, "_ensure_space_async_task_tenant_consistency", new=MagicMock()),
    ):
        result = await service.batch_retry_failed_files(9, [17])

    assert result is True
    retry_task.delay.assert_called_once_with(17)
    require_action.assert_awaited_once_with("rename", "knowledge_file", 17)
    update_status.assert_awaited_once_with(
        [17],
        KnowledgeFileStatus.WAITING,
        "batch_retry_failed_files",
    )
