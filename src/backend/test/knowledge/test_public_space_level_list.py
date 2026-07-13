from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
    UserRoleEnum,
)
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


def _build_service(*, user_id: int = 1) -> KnowledgeSpaceService:
    service = KnowledgeSpaceService.__new__(KnowledgeSpaceService)
    service.login_user = SimpleNamespace(user_id=user_id)
    return service


@pytest.mark.asyncio
async def test_public_space_list_includes_user_role_from_membership():
    space = Knowledge(
        id=214,
        name="Public space",
        user_id=22,
        type=KnowledgeTypeEnum.SPACE.value,
    )
    member = SpaceChannelMember(
        id=275,
        business_id="214",
        business_type=BusinessTypeEnum.SPACE,
        user_id=1,
        user_role=UserRoleEnum.CREATOR,
        status=MembershipStatusEnum.ACTIVE,
    )
    service = _build_service(user_id=1)

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.aget_space_ids_by_level",
            new=AsyncMock(return_value=[214]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_get_spaces_by_ids",
            new=AsyncMock(return_value=[space]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_get_user_space_members",
            new=AsyncMock(return_value=[member]),
        ) as memberships,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.get_permission_levels",
            new=AsyncMock(),
        ) as permission_levels,
    ):
        result = await service.get_public_spaces("update_time")

    memberships.assert_awaited_once_with(1)
    permission_levels.assert_not_called()
    assert result[0]["user_role"] == UserRoleEnum.CREATOR.value
    assert result[0]["space_level"] == "public"
    assert "file_num" not in result[0]
    assert "department_name" not in result[0]


@pytest.mark.asyncio
async def test_public_space_list_resolves_user_role_from_permission_level():
    space = Knowledge(
        id=10,
        name="Public space",
        user_id=22,
        type=KnowledgeTypeEnum.SPACE.value,
    )
    service = _build_service(user_id=1)

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.aget_space_ids_by_level",
            new=AsyncMock(return_value=[10]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_get_spaces_by_ids",
            new=AsyncMock(return_value=[space]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_get_user_space_members",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.get_permission_levels",
            new=AsyncMock(return_value={"10": "owner"}),
        ) as permission_levels,
    ):
        result = await service.get_public_spaces("update_time")

    permission_levels.assert_awaited_once()
    assert result == [{**space.model_dump(), "space_level": "public", "user_role": "admin"}]


@pytest.mark.asyncio
async def test_public_space_list_marks_space_owner_as_creator():
    space = Knowledge(
        id=10,
        name="Public space",
        user_id=1,
        type=KnowledgeTypeEnum.SPACE.value,
    )
    service = _build_service(user_id=1)

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.aget_space_ids_by_level",
            new=AsyncMock(return_value=[10]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_get_spaces_by_ids",
            new=AsyncMock(return_value=[space]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_get_user_space_members",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.get_permission_levels",
            new=AsyncMock(),
        ) as permission_levels,
    ):
        result = await service.get_public_spaces("update_time")

    permission_levels.assert_not_called()
    assert result[0]["user_role"] == UserRoleEnum.CREATOR.value
