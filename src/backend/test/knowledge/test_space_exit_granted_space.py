"""Exiting a space you were granted rather than joined must say so.

The joined list is resolved from the F048 `visible` decision, so it also holds
spaces reached through a Grant — a department grant, say — which carry no
membership row. Exiting one of those revoked nothing, deleted no row, and still
returned 200, so the client toasted "exited" and the space reappeared on the
very next refresh.
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


async def test_exiting_a_granted_space_is_refused_with_its_own_code():
    delete_member = AsyncMock(return_value=0)
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
            "bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.delete_space_member",
            delete_member,
        ),
        pytest.raises(SpaceGrantedNotJoinedError) as exc_info,
    ):
        await _service().unsubscribe_space(_SPACE_ID)

    assert exc_info.value.code == 18080
    # It must not pretend to act: no revoke, no delete, no "exited" toast.
    delete_member.assert_not_awaited()


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
