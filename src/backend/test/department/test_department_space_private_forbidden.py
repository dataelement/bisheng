from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.knowledge_space import DepartmentSpacePrivateForbiddenError
from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum, KnowledgeTypeEnum
from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
    DepartmentKnowledgeSpaceBatchCreateReq,
    DepartmentKnowledgeSpaceBatchItem,
)
from bisheng.knowledge.domain.services.department_knowledge_space_service import (
    DepartmentKnowledgeSpaceService,
)
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


def _login_user():
    return SimpleNamespace(
        user_id=1,
        user_name="admin",
        tenant_id=1,
        is_admin=lambda: True,
    )


def _space(auth_type: AuthTypeEnum):
    return SimpleNamespace(
        id=101,
        type=KnowledgeTypeEnum.SPACE.value,
        name="Department space",
        description="",
        icon=None,
        auth_type=auth_type,
        is_released=False,
        auto_tag_enabled=False,
        auto_tag_library_id=None,
    )


async def test_department_space_batch_create_rejects_explicit_private_before_any_write():
    req = DepartmentKnowledgeSpaceBatchCreateReq(
        items=[
            DepartmentKnowledgeSpaceBatchItem(
                department_id=10,
                auth_type=AuthTypeEnum.PRIVATE,
            )
        ]
    )

    with (
        patch.object(DepartmentKnowledgeSpaceService, "_load_departments", new_callable=AsyncMock) as load_depts,
        patch.object(KnowledgeSpaceService, "create_knowledge_space", new_callable=AsyncMock) as create_space,
    ):
        with pytest.raises(DepartmentSpacePrivateForbiddenError):
            await DepartmentKnowledgeSpaceService.batch_create_spaces(
                request=SimpleNamespace(),
                login_user=_login_user(),
                req=req,
            )

    load_depts.assert_not_awaited()
    create_space.assert_not_awaited()


async def test_department_space_update_rejects_public_to_private_before_cleanup_or_write():
    space = _space(AuthTypeEnum.PUBLIC)
    service = KnowledgeSpaceService(request=SimpleNamespace(), login_user=_login_user())

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new=AsyncMock(return_value=space),
        ),
        patch.object(service, "_require_action", new_callable=AsyncMock),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_id",
            new=AsyncMock(return_value=SimpleNamespace(space_id=space.id, department_id=10)),
        ),
        patch.object(service, "_list_space_child_resources", new_callable=AsyncMock) as list_children,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_space",
            new_callable=AsyncMock,
        ) as update_space,
    ):
        with pytest.raises(DepartmentSpacePrivateForbiddenError):
            await service.update_knowledge_space(space.id, auth_type=AuthTypeEnum.PRIVATE)

    assert space.auth_type == AuthTypeEnum.PUBLIC
    list_children.assert_not_awaited()
    update_space.assert_not_awaited()


async def test_department_space_update_rejects_explicit_private_for_historical_private_space():
    space = _space(AuthTypeEnum.PRIVATE)
    service = KnowledgeSpaceService(request=SimpleNamespace(), login_user=_login_user())

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new=AsyncMock(return_value=space),
        ),
        patch.object(service, "_require_action", new_callable=AsyncMock),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_id",
            new=AsyncMock(return_value=SimpleNamespace(space_id=space.id, department_id=10)),
        ),
        patch.object(service, "_list_space_child_resources", new_callable=AsyncMock) as list_children,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_space",
            new_callable=AsyncMock,
        ) as update_space,
    ):
        with pytest.raises(DepartmentSpacePrivateForbiddenError):
            await service.update_knowledge_space(space.id, auth_type=AuthTypeEnum.PRIVATE)

    list_children.assert_not_awaited()
    update_space.assert_not_awaited()


async def test_non_department_space_can_be_changed_to_private():
    space = _space(AuthTypeEnum.PUBLIC)
    service = KnowledgeSpaceService(request=SimpleNamespace(), login_user=_login_user())

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new=AsyncMock(return_value=space),
        ),
        patch.object(service, "_require_action", new_callable=AsyncMock),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_id",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "SpaceChannelMemberDao.async_get_members_by_space",
            new=AsyncMock(return_value=[]),
        ),
        patch.object(service, "_authorized_space_user_ids", new=AsyncMock(return_value=set())),
        patch.object(service, "_list_space_child_resources", new=AsyncMock(return_value=[])),
        patch.object(
            KnowledgeSpaceService,
            "clear_space_authorization_for_private",
            new_callable=AsyncMock,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "SpaceChannelMemberDao.async_delete_non_creator_members",
            new_callable=AsyncMock,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_space",
            new=AsyncMock(side_effect=lambda updated: updated),
        ) as update_space,
        patch.object(service, "_send_space_event_notification", new_callable=AsyncMock),
    ):
        result = await service.update_knowledge_space(space.id, auth_type=AuthTypeEnum.PRIVATE)

    assert result.auth_type == AuthTypeEnum.PRIVATE
    update_space.assert_awaited_once_with(space)


async def test_unrelated_update_preserves_historical_private_department_space():
    space = _space(AuthTypeEnum.PRIVATE)
    service = KnowledgeSpaceService(request=SimpleNamespace(), login_user=_login_user())

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new=AsyncMock(return_value=space),
        ),
        patch.object(service, "_require_action", new_callable=AsyncMock),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_id",
            new=AsyncMock(return_value=SimpleNamespace(space_id=space.id, department_id=10)),
        ) as get_binding,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_space",
            new=AsyncMock(side_effect=lambda updated: updated),
        ) as update_space,
    ):
        result = await service.update_knowledge_space(space.id, name="Renamed historical space")

    assert result.name == "Renamed historical space"
    assert result.auth_type == AuthTypeEnum.PRIVATE
    get_binding.assert_not_awaited()
    update_space.assert_awaited_once_with(space)
