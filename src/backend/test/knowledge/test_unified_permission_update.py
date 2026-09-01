"""F050 Knowledge settings save order and PRIVATE permission contracts."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum, Knowledge, KnowledgeState, KnowledgeTypeEnum
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


def _space() -> Knowledge:
    return Knowledge(
        id=101,
        tenant_id=7,
        user_id=11,
        name="Space",
        type=KnowledgeTypeEnum.SPACE.value,
        state=KnowledgeState.PUBLISHED.value,
        auth_type=AuthTypeEnum.PUBLIC,
        model="3",
    )


def _service() -> KnowledgeSpaceService:
    service = KnowledgeSpaceService(
        request=MagicMock(),
        login_user=SimpleNamespace(user_id=11, tenant_id=7),
    )
    service._require_action = AsyncMock()
    return service


@pytest.fixture(autouse=True)
def _no_department_binding():
    """Turning a space private consults its department binding (a department
    space may never go private). These cases cover the permission projection,
    so report no binding rather than reaching the database."""
    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_id",
        new=AsyncMock(return_value=None),
    ):
        yield


async def test_business_save_failure_does_not_touch_grants_or_memberships() -> None:
    service = _service()
    clear = AsyncMock()
    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new=AsyncMock(return_value=_space()),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_space",
            new=AsyncMock(side_effect=RuntimeError("save failed")),
        ),
        patch.object(KnowledgeSpaceService, "clear_space_authorization_for_private", new=clear),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "SpaceChannelMemberDao.async_delete_non_creator_members",
            new_callable=AsyncMock,
        ) as remove_members,
    ):
        with pytest.raises(RuntimeError, match="save failed"):
            await service.update_knowledge_space(101, auth_type=AuthTypeEnum.PRIVATE)

    clear.assert_not_awaited()
    remove_members.assert_not_awaited()
    service._require_action.assert_awaited_once_with("knowledge_space", 101, "edit")


async def test_private_projection_commits_before_membership_cleanup() -> None:
    service = _service()
    order = []
    space = _space()

    async def save(value):
        order.append("business")
        return value

    async def clear(**kwargs):
        order.append("permission")

    async def remove_members(_space_id):
        order.append("membership")

    service._authorized_space_user_ids = AsyncMock(return_value=set())
    service._list_space_child_resources = AsyncMock(return_value=[])
    service._send_space_event_notification = AsyncMock()
    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new=AsyncMock(return_value=space),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_space",
            new=AsyncMock(side_effect=save),
        ),
        patch.object(KnowledgeSpaceService, "clear_space_authorization_for_private", new=clear),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_get_members_by_space",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "SpaceChannelMemberDao.async_delete_non_creator_members",
            new=AsyncMock(side_effect=remove_members),
        ),
    ):
        result = await service.update_knowledge_space(101, auth_type=AuthTypeEnum.PRIVATE)

    assert result.auth_type == AuthTypeEnum.PRIVATE
    assert order == ["business", "permission", "membership"]


async def test_private_projection_failure_preserves_membership_rows() -> None:
    service = _service()
    service._authorized_space_user_ids = AsyncMock(return_value=set())
    service._list_space_child_resources = AsyncMock(return_value=[])
    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new=AsyncMock(return_value=_space()),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_space",
            new=AsyncMock(side_effect=lambda value: value),
        ),
        patch.object(
            KnowledgeSpaceService,
            "clear_space_authorization_for_private",
            new=AsyncMock(side_effect=RuntimeError("projection failed")),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_get_members_by_space",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "SpaceChannelMemberDao.async_delete_non_creator_members",
            new_callable=AsyncMock,
        ) as remove_members,
    ):
        with pytest.raises(RuntimeError, match="projection failed"):
            await service.update_knowledge_space(101, auth_type=AuthTypeEnum.PRIVATE)

    remove_members.assert_not_awaited()
