from unittest.mock import AsyncMock, patch

import pytest
from test.test_knowledge_space_service import (
    _load_service_class,
    _make_file,
    _make_login_user,
    _make_space,
)
from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum


@pytest.fixture
def service():
    return _load_service_class()(None, _make_login_user())


@pytest.mark.asyncio
async def test_department_space_upload_does_not_create_approval_request(service):
    space = _make_space(auth_type=AuthTypeEnum.PUBLIC)
    added_file = _make_file(file_id=101, knowledge_id=1, file_name="doc.txt")
    added_file.file_size = 1

    with patch.object(
        service, "_require_permission_id", new_callable=AsyncMock,
    ), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
        new_callable=AsyncMock,
        return_value=space,
    ), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.SpaceFileDao.get_user_total_file_size",
        new_callable=AsyncMock,
        return_value=0,
    ), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.QuotaService.get_knowledge_space_upload_limit_bytes",
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeService.process_one_file",
        return_value=added_file,
    ) as mock_process_one_file, patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.batch_write_tuples",
        new_callable=AsyncMock,
    ), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.OwnerService.write_owner_tuple",
        new_callable=AsyncMock,
    ), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id",
        new_callable=AsyncMock,
    ), patch(
        "bisheng.approval.domain.services.approval_service.ApprovalService.create_department_space_upload_request",
        new_callable=AsyncMock,
    ) as mock_create_request:
        result = await service.add_file(1, ["/tmp/doc.txt"])

    assert result[0].id == 101
    mock_process_one_file.assert_called_once()
    mock_create_request.assert_not_called()
