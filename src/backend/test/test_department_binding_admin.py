from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

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
    with pytest.raises(Exception):
        await Svc.bind_space_to_department(_non_admin(), space_id=10, department_id=3)


@pytest.mark.asyncio
async def test_bind_rejects_already_bound_space():
    with patch(f"{MOD}.KnowledgeSpaceScopeDao.aget_space_ids_by_level", new=AsyncMock(return_value=[10])), \
         patch(f"{MOD}.DepartmentKnowledgeSpaceDao.aget_by_space_id", new=AsyncMock(return_value=object())), \
         patch(f"{MOD}.DepartmentKnowledgeSpaceDao.aget_by_department_id", new=AsyncMock(return_value=None)), \
         patch(f"{MOD}.DepartmentDao.aget_by_id", new=AsyncMock(return_value=SimpleNamespace(id=3, name="d", status="active"))):
        with pytest.raises(Exception):
            await Svc.bind_space_to_department(_admin(), space_id=10, department_id=3)


@pytest.mark.asyncio
async def test_bind_success_creates_row():
    with patch(f"{MOD}.KnowledgeSpaceScopeDao.aget_space_ids_by_level", new=AsyncMock(return_value=[10])), \
         patch(f"{MOD}.DepartmentKnowledgeSpaceDao.aget_by_space_id", new=AsyncMock(return_value=None)), \
         patch(f"{MOD}.DepartmentKnowledgeSpaceDao.aget_by_department_id", new=AsyncMock(return_value=None)), \
         patch(f"{MOD}.DepartmentDao.aget_by_id", new=AsyncMock(return_value=SimpleNamespace(id=3, name="d", status="active"))), \
         patch(f"{MOD}.DepartmentKnowledgeSpaceDao.acreate", new=AsyncMock(return_value=SimpleNamespace(space_id=10, department_id=3))) as create:
        await Svc.bind_space_to_department(_admin(), space_id=10, department_id=3)
        create.assert_awaited_once()


@pytest.mark.asyncio
async def test_bind_rejects_non_team_space():
    with patch(f"{MOD}.KnowledgeSpaceScopeDao.aget_space_ids_by_level", new=AsyncMock(return_value=[])):  # 10 不在 team 集合
        with pytest.raises(Exception):
            await Svc.bind_space_to_department(_admin(), space_id=10, department_id=3)


@pytest.mark.asyncio
async def test_unbind_calls_dao():
    with patch(f"{MOD}.DepartmentKnowledgeSpaceDao.adelete_by_space_id", new=AsyncMock(return_value=True)) as d:
        await Svc.unbind_space(_admin(), space_id=10)
        d.assert_awaited_once_with(10)


@pytest.mark.asyncio
async def test_list_bindings_assembles_names():
    with patch(f"{MOD}.DepartmentKnowledgeSpaceDao.aget_all", new=AsyncMock(return_value=[
             SimpleNamespace(space_id=10, department_id=3, created_by=1, create_time="2026-01-01")])), \
         patch(f"{MOD}.KnowledgeDao.async_get_spaces_by_ids", new=AsyncMock(return_value=[
             SimpleNamespace(id=10, name="空间A")])), \
         patch(f"{MOD}.DepartmentDao.aget_by_ids", new=AsyncMock(return_value=[
             SimpleNamespace(id=3, name="科室B")])):
        result = await Svc.list_bindings(_admin())
    assert result == [{
        "space_id": 10, "space_name": "空间A",
        "department_id": 3, "department_name": "科室B",
        "created_by": 1, "create_time": "2026-01-01",
    }]

    # 空表分支：无绑定行时直接返回 []
    with patch(f"{MOD}.DepartmentKnowledgeSpaceDao.aget_all", new=AsyncMock(return_value=[])):
        assert await Svc.list_bindings(_admin()) == []


@pytest.mark.asyncio
async def test_list_bindable_team_spaces_excludes_bound_and_filters_keyword():
    with patch(f"{MOD}.KnowledgeSpaceScopeDao.aget_space_ids_by_level", new=AsyncMock(return_value=[10, 11])), \
         patch(f"{MOD}.DepartmentKnowledgeSpaceDao.aget_by_space_ids", new=AsyncMock(return_value=[
             SimpleNamespace(space_id=10)])), \
         patch(f"{MOD}.KnowledgeDao.async_get_spaces_by_ids", new=AsyncMock(return_value=[
             SimpleNamespace(id=11, name="自由库X")])):
        # 10 已绑定被排除，只剩 11
        assert await Svc.list_bindable_team_spaces(_admin()) == [{"space_id": 11, "name": "自由库X"}]
        # keyword 子串命中
        assert await Svc.list_bindable_team_spaces(_admin(), keyword="自由") == [{"space_id": 11, "name": "自由库X"}]
        # keyword 不命中
        assert await Svc.list_bindable_team_spaces(_admin(), keyword="不存在") == []


@pytest.mark.asyncio
async def test_list_departments_returns_active():
    with patch(f"{MOD}.DepartmentDao.aget_all_active", new=AsyncMock(return_value=[
             SimpleNamespace(id=3, name="科室B"), SimpleNamespace(id=4, name="科室C")])):
        result = await Svc.list_departments(_admin())
    assert result == [{"id": 3, "name": "科室B"}, {"id": 4, "name": "科室C"}]
