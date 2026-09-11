"""Exiting a space you were granted rather than joined.

The joined list is resolved from the F048 `visible` decision, so it also holds
spaces reached through a Grant, which carry no membership row. Exiting one of
those revoked nothing, deleted no row, and still returned 200, so the client
toasted "exited" and the space reappeared on the very next refresh.

Refusing outright was too broad, though: accepting an invitation also leaves no
membership row, and that grant is the invitee's own to give up. The refusal now
belongs to the case it was written for — access held through a department or a
group, which an individual cannot resign from.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.knowledge_space import (
    SpaceGrantedNotJoinedError,
    SpacePermissionDeniedError,
)
from bisheng.common.models.space_channel_member import UserRoleEnum
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

_SPACE_ID = 156  # 部门编辑者
_VIEWER = 150041  # granted through their department, never joined


def _service(login_user_id: int = _VIEWER) -> KnowledgeSpaceService:
    service = object.__new__(KnowledgeSpaceService)
    service.login_user = SimpleNamespace(user_id=login_user_id, user_name="gzx006", tenant_id=1)
    return service


def _space(creator_id: int = 1):
    return SimpleNamespace(
        id=_SPACE_ID,
        type=KnowledgeTypeEnum.SPACE.value,
        user_id=creator_id,
        name="部门编辑者",
    )


def _adapter(*, removed: bool):
    return SimpleNamespace(remove_own_sources=AsyncMock(return_value=removed))


async def test_exiting_a_department_granted_space_is_refused_with_its_own_code():
    delete_member = AsyncMock(return_value=0)
    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.get_f048_resource_adapter",
            AsyncMock(return_value=_adapter(removed=False)),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            AsyncMock(return_value=_space()),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_find_member",
            AsyncMock(return_value=None),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.delete_space_member",
            delete_member,
        ),
        pytest.raises(SpaceGrantedNotJoinedError) as exc_info,
    ):
        await _service().unsubscribe_space(_SPACE_ID)

    assert exc_info.value.code == 18080
    # It must not pretend to act: no revoke, no delete, no "exited" toast.
    delete_member.assert_not_awaited()


async def test_somebody_who_accepted_an_invitation_can_leave():
    """Their access is a grant of their own, so dropping it is leaving."""

    adapter = _adapter(removed=True)
    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            AsyncMock(return_value=_space()),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_find_member",
            AsyncMock(return_value=None),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.get_f048_resource_adapter",
            AsyncMock(return_value=adapter),
        ),
    ):
        assert await _service().unsubscribe_space(_SPACE_ID) is True

    adapter.remove_own_sources.assert_awaited_once_with(
        resource_id=str(_SPACE_ID),
        subject_user_id=_VIEWER,
    )


async def test_a_real_member_still_exits():
    revoke = AsyncMock(return_value=None)
    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            AsyncMock(return_value=_space()),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_find_member",
            AsyncMock(return_value=SimpleNamespace(id=9, user_role=UserRoleEnum.MEMBER)),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.delete_space_member",
            AsyncMock(return_value=1),
        ),
        patch.object(KnowledgeSpaceService, "_revoke_direct_space_user_permissions", revoke),
    ):
        assert await _service().unsubscribe_space(_SPACE_ID) == 1

    revoke.assert_awaited_once()


async def test_the_creator_is_still_refused_for_being_the_creator():
    """The creator guard runs first and keeps its own, different reason."""
    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            AsyncMock(return_value=_space(creator_id=_VIEWER)),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_find_member",
            AsyncMock(return_value=None),
        ),
        pytest.raises(SpacePermissionDeniedError),
    ):
        await _service().unsubscribe_space(_SPACE_ID)
