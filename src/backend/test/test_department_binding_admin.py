from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from bisheng.common.errcode.department import DepartmentNotFoundError
from bisheng.common.errcode.knowledge_space import (
    DepartmentKnowledgeSpaceExistsError,
    SpaceNotFoundError,
)
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum
from bisheng.knowledge.domain.services.department_knowledge_space_service import (
    DepartmentKnowledgeSpaceService as Svc,
)

MOD = "bisheng.knowledge.domain.services.department_knowledge_space_service"


def _admin():
    return SimpleNamespace(user_id=1, tenant_id=1, is_admin=lambda: True)


def _non_admin():
    return SimpleNamespace(user_id=2, tenant_id=1, is_admin=lambda: False)


@pytest.mark.asyncio
async def test_bind_requires_admin():
    # The real errcode module is pre-mocked as MagicMock by conftest; patch the
    # service-local reference to a concrete exception class so raises() works.
    class _Unauthorized(Exception):
        pass

    with patch(f"{MOD}.UnAuthorizedError", _Unauthorized):
        with pytest.raises(_Unauthorized):
            await Svc.bind_space_to_department(_non_admin(), space_id=10, department_id=3)


@pytest.mark.asyncio
async def test_bind_rejects_already_bound_space():
    with (
        patch(f"{MOD}.KnowledgeSpaceScopeDao.aget_space_ids_by_level", new=AsyncMock(return_value=[10])),
        patch(f"{MOD}.DepartmentKnowledgeSpaceDao.aget_by_space_id", new=AsyncMock(return_value=object())),
        patch(
            f"{MOD}.DepartmentDao.aget_by_id",
            new=AsyncMock(return_value=SimpleNamespace(id=3, name="d", status="active")),
        ),
    ):
        with pytest.raises(DepartmentKnowledgeSpaceExistsError):
            await Svc.bind_space_to_department(_admin(), space_id=10, department_id=3)


@pytest.mark.asyncio
async def test_bind_success_creates_row():
    with (
        patch(f"{MOD}.KnowledgeSpaceScopeDao.aget_space_ids_by_level", new=AsyncMock(return_value=[10])),
        patch(f"{MOD}.DepartmentKnowledgeSpaceDao.aget_by_space_id", new=AsyncMock(return_value=None)),
        patch(
            f"{MOD}.DepartmentDao.aget_by_id",
            new=AsyncMock(return_value=SimpleNamespace(id=3, name="d", status="active")),
        ),
        patch(
            f"{MOD}.DepartmentKnowledgeSpaceDao.acreate",
            new=AsyncMock(return_value=SimpleNamespace(space_id=10, department_id=3)),
        ) as create,
        patch(f"{MOD}.KnowledgeSpaceScopeDao.aupdate_level", new=AsyncMock()) as update_level,
    ):
        await Svc.bind_space_to_department(_admin(), space_id=10, department_id=3)
        create.assert_awaited_once()
        update_level.assert_awaited_once_with(10, KnowledgeSpaceLevelEnum.TEAM_KS)


@pytest.mark.asyncio
async def test_bind_rejects_non_team_space():
    with patch(
        f"{MOD}.KnowledgeSpaceScopeDao.aget_space_ids_by_level", new=AsyncMock(return_value=[])
    ):  # 10 is not in the team set
        with pytest.raises(SpaceNotFoundError):
            await Svc.bind_space_to_department(_admin(), space_id=10, department_id=3)


@pytest.mark.asyncio
async def test_unbind_calls_dao():
    with patch(f"{MOD}.DepartmentKnowledgeSpaceDao.adelete_by_space_id", new=AsyncMock(return_value=True)) as d:
        await Svc.unbind_space(_admin(), space_id=10)
        d.assert_awaited_once_with(10)


@pytest.mark.asyncio
async def test_rebind_requires_admin():
    class _Unauthorized(Exception):
        pass

    with patch(f"{MOD}.UnAuthorizedError", _Unauthorized):
        with pytest.raises(_Unauthorized):
            await Svc.rebind_space_to_department(request=Mock(), login_user=_non_admin(), space_id=10, department_id=4)


@pytest.mark.asyncio
async def test_rebind_rejects_unbound_space():
    with patch(f"{MOD}.DepartmentKnowledgeSpaceDao.aget_by_space_id", new=AsyncMock(return_value=None)):
        with pytest.raises(SpaceNotFoundError):
            await Svc.rebind_space_to_department(request=Mock(), login_user=_admin(), space_id=10, department_id=4)


@pytest.mark.asyncio
async def test_rebind_rejects_target_bound_by_other_space():
    with (
        patch(
            f"{MOD}.DepartmentKnowledgeSpaceDao.aget_by_space_id",
            new=AsyncMock(return_value=SimpleNamespace(space_id=10, department_id=3)),
        ),
        patch(
            f"{MOD}.DepartmentDao.aget_by_id",
            new=AsyncMock(return_value=SimpleNamespace(id=4, name="科室D", status="active")),
        ),
        patch(
            f"{MOD}.DepartmentKnowledgeSpaceDao.aget_by_department_id",
            new=AsyncMock(return_value=SimpleNamespace(space_id=99, department_id=4)),
        ),
    ):
        with pytest.raises(DepartmentKnowledgeSpaceExistsError):
            await Svc.rebind_space_to_department(request=Mock(), login_user=_admin(), space_id=10, department_id=4)


@pytest.mark.asyncio
async def test_rebind_rejects_archived_target_department():
    with (
        patch(
            f"{MOD}.DepartmentKnowledgeSpaceDao.aget_by_space_id",
            new=AsyncMock(return_value=SimpleNamespace(space_id=10, department_id=3)),
        ),
        patch(
            f"{MOD}.DepartmentDao.aget_by_id",
            new=AsyncMock(return_value=SimpleNamespace(id=4, name="科室D", status="archived")),
        ),
    ):
        with pytest.raises(DepartmentNotFoundError):
            await Svc.rebind_space_to_department(request=Mock(), login_user=_admin(), space_id=10, department_id=4)


@pytest.mark.asyncio
async def test_rebind_success_updates_binding():
    current_binding = SimpleNamespace(space_id=10, department_id=3)
    with (
        patch(f"{MOD}.DepartmentKnowledgeSpaceDao.aget_by_space_id", new=AsyncMock(return_value=current_binding)),
        patch(
            f"{MOD}.DepartmentDao.aget_by_id",
            new=AsyncMock(return_value=SimpleNamespace(id=4, name="科室D", status="active")),
        ),
        patch(f"{MOD}.DepartmentKnowledgeSpaceDao.aget_by_department_id", new=AsyncMock(return_value=None)),
        patch(f"{MOD}.KnowledgeSpaceService") as ServiceMock,
    ):
        instance = ServiceMock.return_value
        instance.update_knowledge_space = AsyncMock()
        instance.get_space_info = AsyncMock(return_value=SimpleNamespace(id=10, department_id=4))
        result = await Svc.rebind_space_to_department(request=Mock(), login_user=_admin(), space_id=10, department_id=4)
        instance.update_knowledge_space.assert_awaited_once_with(space_id=10, department_id=4)
        instance.get_space_info.assert_awaited_once_with(10)
        assert result.id == 10


@pytest.mark.asyncio
async def test_rebind_idempotent_when_same_department():
    current_binding = SimpleNamespace(space_id=10, department_id=3)
    with (
        patch(f"{MOD}.DepartmentKnowledgeSpaceDao.aget_by_space_id", new=AsyncMock(return_value=current_binding)),
        patch(
            f"{MOD}.DepartmentDao.aget_by_id",
            new=AsyncMock(return_value=SimpleNamespace(id=3, name="科室C", status="active")),
        ),
        patch(f"{MOD}.DepartmentKnowledgeSpaceDao.aget_by_department_id", new=AsyncMock(return_value=current_binding)),
        patch(f"{MOD}.KnowledgeSpaceService") as ServiceMock,
    ):
        instance = ServiceMock.return_value
        instance.update_knowledge_space = AsyncMock()
        instance.get_space_info = AsyncMock(return_value=SimpleNamespace(id=10, department_id=3))
        result = await Svc.rebind_space_to_department(request=Mock(), login_user=_admin(), space_id=10, department_id=3)
        instance.update_knowledge_space.assert_awaited_once_with(space_id=10, department_id=3)
        assert result.id == 10


@pytest.mark.asyncio
async def test_list_bindings_assembles_names():
    with (
        patch(
            f"{MOD}.DepartmentKnowledgeSpaceDao.aget_all",
            new=AsyncMock(
                return_value=[SimpleNamespace(space_id=10, department_id=3, created_by=1, create_time="2026-01-01")]
            ),
        ),
        patch(
            f"{MOD}.KnowledgeDao.async_get_spaces_by_ids",
            new=AsyncMock(return_value=[SimpleNamespace(id=10, name="空间A")]),
        ),
        patch(f"{MOD}.DepartmentDao.aget_by_ids", new=AsyncMock(return_value=[SimpleNamespace(id=3, name="科室B")])),
    ):
        result = await Svc.list_bindings(_admin())
    assert result == [
        {
            "space_id": 10,
            "space_name": "空间A",
            "department_id": 3,
            "department_name": "科室B",
            "created_by": 1,
            "create_time": "2026-01-01",
        }
    ]

    # Empty table branch: return [] when there are no binding rows
    with patch(f"{MOD}.DepartmentKnowledgeSpaceDao.aget_all", new=AsyncMock(return_value=[])):
        assert await Svc.list_bindings(_admin()) == []


@pytest.mark.asyncio
async def test_list_bindable_team_spaces_excludes_bound_and_filters_keyword():
    with (
        patch(f"{MOD}.KnowledgeSpaceScopeDao.aget_space_ids_by_level", new=AsyncMock(return_value=[10, 11])),
        patch(
            f"{MOD}.DepartmentKnowledgeSpaceDao.aget_by_space_ids",
            new=AsyncMock(return_value=[SimpleNamespace(space_id=10)]),
        ),
        patch(
            f"{MOD}.KnowledgeDao.async_get_spaces_by_ids",
            new=AsyncMock(return_value=[SimpleNamespace(id=11, name="自由库X")]),
        ),
    ):
        # 10 is bound and excluded, only 11 remains
        assert await Svc.list_bindable_team_spaces(_admin()) == [{"space_id": 11, "name": "自由库X"}]
        # keyword substring match
        assert await Svc.list_bindable_team_spaces(_admin(), keyword="自由") == [{"space_id": 11, "name": "自由库X"}]
        # keyword does not match
        assert await Svc.list_bindable_team_spaces(_admin(), keyword="不存在") == []


@pytest.mark.asyncio
async def test_list_departments_returns_active():
    with patch(
        f"{MOD}.DepartmentDao.aget_all_active",
        new=AsyncMock(
            return_value=[
                SimpleNamespace(id=3, name="科室B", parent_id=1, sort_order=2),
                SimpleNamespace(id=1, name="集团", parent_id=None, sort_order=1),
                SimpleNamespace(id=4, name="科室C", parent_id=1, sort_order=1),
            ]
        ),
    ):
        result = await Svc.list_departments(_admin())
    assert result == [
        {
            "id": 1,
            "name": "集团",
            "children": [
                {"id": 4, "name": "科室C", "children": []},
                {"id": 3, "name": "科室B", "children": []},
            ],
        }
    ]
