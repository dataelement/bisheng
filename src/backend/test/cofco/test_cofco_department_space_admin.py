"""Guard the F045 hooks inside KnowledgeSpaceService.

F045's department-space admin logic lives in DepartmentKnowledgeSpaceService,
and test/knowledge/test_department_space_admin.py covers that service on its
own. What it cannot see is whether KnowledgeSpaceService still *calls into* it:
the 2026-09-01 merge of the 3.0 line rebuilt knowledge_space_service.py from the
main-line copy and silently dropped both hooks below, while every F045 test kept
passing. These tests pin the hooks themselves.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.common.errcode.knowledge_space import SpacePendingAdminError
from bisheng.common.models.space_channel_member import UserRoleEnum
from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum, KnowledgeTypeEnum
from bisheng.knowledge.domain.schemas.knowledge_space_schema import KnowledgeSpaceInfoResp
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

_SVC = "bisheng.knowledge.domain.services.knowledge_space_service"
_ADMIN_ID = 9
_SUPER_ADMIN_ID = 1


def _service(user_id: int = _SUPER_ADMIN_ID) -> KnowledgeSpaceService:
    login_user = SimpleNamespace(user_id=user_id, user_name=f"u{user_id}", tenant_id=1)
    return KnowledgeSpaceService(MagicMock(), login_user)


def _space(space_id: int = 101) -> KnowledgeSpaceInfoResp:
    # What the generic formatters produce for a space the super admin created.
    return KnowledgeSpaceInfoResp(
        id=space_id,
        name="dept space",
        user_id=_SUPER_ADMIN_ID,
        user_name="superadmin",
        avatar="avatar.png",
        user_role=UserRoleEnum.CREATOR,
    )


async def _decorate(service: KnowledgeSpaceService, space: KnowledgeSpaceInfoResp, admin_user_id: int | None):
    binding = SimpleNamespace(
        space_id=space.id,
        department_id=5,
        approval_enabled=False,
        sensitive_check_enabled=False,
        is_hidden=False,
        admin_user_id=admin_user_id,
    )
    admin = SimpleNamespace(user_id=_ADMIN_ID, user_name="space admin")
    with (
        patch(f"{_SVC}.DepartmentKnowledgeSpaceDao.aget_by_space_ids", new=AsyncMock(return_value=[binding])),
        patch(f"{_SVC}.DepartmentDao.aget_by_ids", new=AsyncMock(return_value=[SimpleNamespace(id=5, name="D")])),
        patch(f"{_SVC}.UserDao.aget_user_by_ids", new=AsyncMock(return_value=[admin])),
    ):
        await service._decorate_department_metadata([space])
    return space


async def test_department_space_shows_admin_instead_of_creator() -> None:
    space = await _decorate(_service(), _space(), admin_user_id=_ADMIN_ID)

    assert space.user_name == "space admin"
    assert space.avatar is None
    assert space.user_role is None
    assert space.admin_user_id == _ADMIN_ID
    assert space.pending_admin is False


async def test_department_space_admin_keeps_admin_role() -> None:
    space = await _decorate(_service(user_id=_ADMIN_ID), _space(), admin_user_id=_ADMIN_ID)

    assert space.user_role == UserRoleEnum.ADMIN


async def test_pending_admin_space_shows_no_owner() -> None:
    space = await _decorate(_service(), _space(), admin_user_id=None)

    assert space.user_name == ""
    assert space.pending_admin is True


async def test_subscribe_is_blocked_while_department_space_has_no_admin() -> None:
    service = _service(user_id=42)
    gate = MagicMock()
    gate.request_or_pass = AsyncMock()
    service.approval_gate = gate
    space = SimpleNamespace(
        id=101,
        name="dept space",
        type=KnowledgeTypeEnum.SPACE.value,
        auth_type=AuthTypeEnum.APPROVAL,
    )
    with (
        patch(f"{_SVC}.KnowledgeDao.aquery_by_id", new=AsyncMock(return_value=space)),
        patch(f"{_SVC}.SpaceChannelMemberDao.async_find_member", new=AsyncMock(return_value=None)),
        patch(f"{_SVC}.QuotaService.get_effective_quota", new=AsyncMock(return_value=-1)),
        patch(
            "bisheng.knowledge.domain.services.department_knowledge_space_service."
            "DepartmentKnowledgeSpaceDao.aget_by_space_id",
            new=AsyncMock(return_value=SimpleNamespace(admin_user_id=None)),
        ),
    ):
        with pytest.raises(SpacePendingAdminError):
            await service.subscribe_space(101)

    gate.request_or_pass.assert_not_awaited()
