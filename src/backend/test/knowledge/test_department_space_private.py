"""Department-space visibility must not remove the department's access grants."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum, Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

MODULE = "bisheng.knowledge.domain.services.knowledge_space_service"


@pytest.fixture
def service_and_space():
    service = KnowledgeSpaceService(request=MagicMock(), login_user=SimpleNamespace(user_id=11, tenant_id=7))
    service._require_action = AsyncMock()
    service._send_space_event_notification = AsyncMock()
    space = Knowledge(
        id=101,
        tenant_id=7,
        user_id=11,
        name="Department",
        type=KnowledgeTypeEnum.SPACE.value,
        auth_type=AuthTypeEnum.APPROVAL,
        model="3",
    )
    return service, space


async def test_department_private_is_rejected_before_business_or_permission_writes(service_and_space):
    service, space = service_and_space
    with (
        patch(f"{MODULE}.KnowledgeDao.aquery_by_id", new=AsyncMock(return_value=space)),
        patch(
            f"{MODULE}.DepartmentKnowledgeSpaceDao.aget_by_space_id",
            new=AsyncMock(return_value=SimpleNamespace(department_id=8)),
        ),
        patch(f"{MODULE}.KnowledgeDao.async_update_space", new_callable=AsyncMock) as save,
        patch.object(KnowledgeSpaceService, "clear_space_authorization_for_private", new_callable=AsyncMock) as clear,
        patch(f"{MODULE}.SpaceChannelMemberDao.async_delete_non_creator_members", new_callable=AsyncMock) as remove,
    ):
        with pytest.raises(BaseErrorCode) as error:
            await service.update_knowledge_space(101, name="Changed", auth_type=AuthTypeEnum.PRIVATE)
    assert error.value.code == 18081
    assert space.name == "Department"
    assert space.auth_type == AuthTypeEnum.APPROVAL
    save.assert_not_awaited()
    clear.assert_not_awaited()
    remove.assert_not_awaited()
    service._require_action.assert_awaited_once_with("knowledge_space", 101, "edit")


@pytest.mark.parametrize("visibility", [AuthTypeEnum.PUBLIC, AuthTypeEnum.APPROVAL])
async def test_department_shared_modes_remain_editable(service_and_space, visibility):
    service, space = service_and_space
    with (
        patch(f"{MODULE}.KnowledgeDao.aquery_by_id", new=AsyncMock(return_value=space)),
        patch(f"{MODULE}.DepartmentKnowledgeSpaceDao.aget_by_space_id", new_callable=AsyncMock) as lookup,
        patch(f"{MODULE}.KnowledgeDao.async_update_space", new=AsyncMock(side_effect=lambda row: row)) as save,
        patch(f"{MODULE}.SpaceChannelMemberDao.async_get_members_by_space", new=AsyncMock(return_value=[])),
        patch(f"{MODULE}.SpaceChannelMemberDao.async_delete_rejected_members", new_callable=AsyncMock),
    ):
        result = await service.update_knowledge_space(101, auth_type=visibility)
    assert result.auth_type == visibility
    save.assert_awaited_once()
    lookup.assert_not_awaited()


async def test_permissions_are_checked_before_department_binding(service_and_space):
    service, space = service_and_space
    service._require_action.side_effect = SpacePermissionDeniedError()
    with (
        patch(f"{MODULE}.KnowledgeDao.aquery_by_id", new=AsyncMock(return_value=space)),
        patch(f"{MODULE}.DepartmentKnowledgeSpaceDao.aget_by_space_id", new_callable=AsyncMock) as lookup,
    ):
        with pytest.raises(SpacePermissionDeniedError):
            await service.update_knowledge_space(101, auth_type=AuthTypeEnum.PRIVATE)
    lookup.assert_not_awaited()
