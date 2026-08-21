"""Tests for batch accept/reject alias rename."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.common.errcode.knowledge_space import (
    SpaceFileNameDuplicateError,
    SpacePermissionDeniedError,
)
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


def _make_file(
    file_id: int,
    *,
    alias_name: str | None = "规范名称.pdf",
    file_name: str = "raw.pdf",
    knowledge_id: int = 1,
    file_type: int = FileType.FILE.value,
) -> KnowledgeFile:
    record = MagicMock(spec=KnowledgeFile)
    record.id = file_id
    record.alias_name = alias_name
    record.file_name = file_name
    record.knowledge_id = knowledge_id
    record.file_type = file_type
    record.file_source = 0
    record.file_level_path = "/1"
    record.tenant_id = 1
    record.user_metadata = {}
    record.reference_document_id = None
    record.status = 1
    return record


@pytest.fixture
def service() -> KnowledgeSpaceService:
    login_user = MagicMock()
    login_user.user_id = 10
    login_user.user_name = "tester"
    login_user.tenant_id = 1
    return KnowledgeSpaceService(MagicMock(), login_user)


@pytest.mark.asyncio
async def test_batch_accept_alias_rename_success(service: KnowledgeSpaceService) -> None:
    files = [_make_file(1), _make_file(2, alias_name="规范2.pdf", file_name="raw2.pdf")]

    with patch.object(service, "_require_read_permission", new_callable=AsyncMock), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
        new_callable=AsyncMock,
        return_value=MagicMock(id=1),
    ), patch.object(service, "_ensure_space_async_task_tenant_consistency"), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.aget_file_by_ids",
        new_callable=AsyncMock,
        return_value=files,
    ), patch.object(
        service, "_ensure_alias_rename_permission", new_callable=AsyncMock, return_value=None
    ), patch.object(service, "_apply_accept_alias_rename", new_callable=AsyncMock) as apply_mock, patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id",
        new_callable=AsyncMock,
    ), patch.object(service, "update_folder_update_time", new_callable=AsyncMock), patch.object(
        service, "_check_filename_sensitive_words"
    ), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.SpaceFileDao.count_file_by_name",
        new_callable=AsyncMock,
        return_value=0,
    ):
        result = await service.batch_accept_alias_rename(1, [1, 2])

    assert result.succeeded_ids == [1, 2]
    assert result.skipped_ids == []
    assert result.failed == []
    assert apply_mock.await_count == 2


@pytest.mark.asyncio
async def test_batch_accept_alias_rename_skips_without_alias(service: KnowledgeSpaceService) -> None:
    files = [_make_file(1, alias_name=None)]

    with patch.object(service, "_require_read_permission", new_callable=AsyncMock), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
        new_callable=AsyncMock,
        return_value=MagicMock(id=1),
    ), patch.object(service, "_ensure_space_async_task_tenant_consistency"), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.aget_file_by_ids",
        new_callable=AsyncMock,
        return_value=files,
    ):
        result = await service.batch_accept_alias_rename(1, [1])

    assert result.succeeded_ids == []
    assert result.skipped_ids == [1]
    assert result.failed == []


@pytest.mark.asyncio
async def test_batch_accept_alias_rename_duplicate_within_batch(
    service: KnowledgeSpaceService,
) -> None:
    files = [
        _make_file(1, alias_name="same.pdf", file_name="a.pdf"),
        _make_file(2, alias_name="same.pdf", file_name="b.pdf"),
    ]

    with patch.object(service, "_require_read_permission", new_callable=AsyncMock), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
        new_callable=AsyncMock,
        return_value=MagicMock(id=1),
    ), patch.object(service, "_ensure_space_async_task_tenant_consistency"), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.aget_file_by_ids",
        new_callable=AsyncMock,
        return_value=files,
    ), patch.object(
        service, "_ensure_alias_rename_permission", new_callable=AsyncMock, return_value=None
    ), patch.object(service, "_apply_accept_alias_rename", new_callable=AsyncMock), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id",
        new_callable=AsyncMock,
    ), patch.object(service, "update_folder_update_time", new_callable=AsyncMock), patch.object(
        service, "_check_filename_sensitive_words"
    ), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.SpaceFileDao.count_file_by_name",
        new_callable=AsyncMock,
        return_value=0,
    ):
        result = await service.batch_accept_alias_rename(1, [1, 2])

    assert result.succeeded_ids == [1]
    assert result.failed[0].file_id == 2
    assert result.failed[0].reason_code == "duplicate_name"


@pytest.mark.asyncio
async def test_batch_reject_alias_rename_permission_denied(service: KnowledgeSpaceService) -> None:
    files = [_make_file(1)]

    with patch.object(service, "_require_read_permission", new_callable=AsyncMock), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
        new_callable=AsyncMock,
        return_value=MagicMock(id=1),
    ), patch.object(service, "_ensure_space_async_task_tenant_consistency"), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.aget_file_by_ids",
        new_callable=AsyncMock,
        return_value=files,
    ), patch.object(
        service,
        "_ensure_alias_rename_permission",
        new_callable=AsyncMock,
        side_effect=SpacePermissionDeniedError(),
    ):
        result = await service.batch_reject_alias_rename(1, [1])

    assert result.succeeded_ids == []
    assert result.failed[0].reason_code == "permission_denied"


@pytest.mark.asyncio
async def test_batch_accept_alias_rename_duplicate_in_space(service: KnowledgeSpaceService) -> None:
    files = [_make_file(1)]

    with patch.object(service, "_require_read_permission", new_callable=AsyncMock), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
        new_callable=AsyncMock,
        return_value=MagicMock(id=1),
    ), patch.object(service, "_ensure_space_async_task_tenant_consistency"), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.aget_file_by_ids",
        new_callable=AsyncMock,
        return_value=files,
    ), patch.object(
        service, "_ensure_alias_rename_permission", new_callable=AsyncMock, return_value=None
    ), patch.object(service, "_check_filename_sensitive_words"), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.SpaceFileDao.count_file_by_name",
        new_callable=AsyncMock,
        return_value=1,
    ):
        result = await service.batch_accept_alias_rename(1, [1])

    assert result.succeeded_ids == []
    assert result.failed[0].reason_code == "duplicate_name"
