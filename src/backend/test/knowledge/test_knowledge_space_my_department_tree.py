from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


def _login_user(user_id: int = 7, tenant_id: int = 1, is_admin: bool = False):
    return SimpleNamespace(user_id=user_id, tenant_id=tenant_id, is_admin=lambda: is_admin)


def _department(
    dept_id: int,
    *,
    name: str,
    parent_id: int | None = None,
    path: str = "",
    sort_order: int = 0,
    dept_external_id: str = "",
):
    return SimpleNamespace(
        id=dept_id,
        dept_id=dept_external_id or f"BS@{dept_id}",
        name=name,
        parent_id=parent_id,
        path=path or f"/{dept_id}/",
        sort_order=sort_order,
        status="active",
    )


def _user_department(department_id: int):
    return SimpleNamespace(department_id=department_id)


def _binding(department_id: int, space_id: int):
    return SimpleNamespace(department_id=department_id, space_id=space_id)


@pytest.fixture
def mock_session():
    """Provide a mocked async DB session that returns empty member counts."""
    session = MagicMock()
    exec_result = MagicMock()
    exec_result.all.return_value = []
    session.exec = AsyncMock(return_value=exec_result)

    context_manager = MagicMock()
    context_manager.__aenter__ = AsyncMock(return_value=session)
    context_manager.__aexit__ = AsyncMock(return_value=False)
    return context_manager


@pytest.mark.asyncio
async def test_admin_sees_all_departments(mock_session) -> None:
    login_user = _login_user(is_admin=True)
    svc = KnowledgeSpaceService(request=None, login_user=login_user)

    departments = [
        _department(1, name="研发部", path="/1/"),
        _department(2, name="前端组", parent_id=1, path="/1/2/"),
        _department(3, name="市场部", path="/3/"),
    ]

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.UserDepartmentDao.aget_user_departments",
            new=AsyncMock(return_value=[]),
        ) as mock_user_depts,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_active_by_tenant",
            new=AsyncMock(return_value=departments),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_department_ids",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.get_async_db_session",
            return_value=mock_session,
        ),
    ):
        result = await svc.get_my_department_tree_for_create()

    mock_user_depts.assert_not_awaited()
    assert result["bound_department_ids"] == []
    assert len(result["data"]) == 2
    ids = {node["id"] for node in result["data"]}
    assert ids == {1, 3}


@pytest.mark.asyncio
async def test_empty_when_user_has_no_departments(mock_session) -> None:
    login_user = _login_user()
    svc = KnowledgeSpaceService(request=None, login_user=login_user)

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.UserDepartmentDao.aget_user_departments",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.get_async_db_session",
            return_value=mock_session,
        ),
    ):
        result = await svc.get_my_department_tree_for_create()

    assert result == {"data": [], "bound_department_ids": []}


@pytest.mark.asyncio
async def test_returns_user_department_subtree(mock_session) -> None:
    login_user = _login_user()
    svc = KnowledgeSpaceService(request=None, login_user=login_user)

    # User belongs to department 1. Department 2 is a child of 1; department 3 is unrelated.
    departments = [
        _department(1, name="研发部", path="/1/", sort_order=1),
        _department(2, name="前端组", parent_id=1, path="/1/2/", sort_order=1),
        _department(3, name="市场部", path="/3/", sort_order=1),
    ]

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.UserDepartmentDao.aget_user_departments",
            new=AsyncMock(return_value=[_user_department(1)]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_active_by_tenant",
            new=AsyncMock(return_value=departments),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_department_ids",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.get_async_db_session",
            return_value=mock_session,
        ),
    ):
        result = await svc.get_my_department_tree_for_create()

    assert result["bound_department_ids"] == []
    assert len(result["data"]) == 1
    root = result["data"][0]
    assert root["id"] == 1
    assert root["name"] == "研发部"
    assert len(root["children"]) == 1
    assert root["children"][0]["id"] == 2
    assert root["children"][0]["name"] == "前端组"


@pytest.mark.asyncio
async def test_marks_bound_departments(mock_session) -> None:
    login_user = _login_user()
    svc = KnowledgeSpaceService(request=None, login_user=login_user)

    departments = [
        _department(1, name="研发部", path="/1/"),
        _department(2, name="前端组", parent_id=1, path="/1/2/"),
    ]

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.UserDepartmentDao.aget_user_departments",
            new=AsyncMock(return_value=[_user_department(1)]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_active_by_tenant",
            new=AsyncMock(return_value=departments),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_department_ids",
            new=AsyncMock(return_value=[_binding(2, 100)]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.get_async_db_session",
            return_value=mock_session,
        ),
    ):
        result = await svc.get_my_department_tree_for_create()

    assert result["bound_department_ids"] == [2]


@pytest.mark.asyncio
async def test_exclude_space_id_omits_current_binding(mock_session) -> None:
    login_user = _login_user()
    svc = KnowledgeSpaceService(request=None, login_user=login_user)

    departments = [
        _department(1, name="研发部", path="/1/"),
        _department(2, name="前端组", parent_id=1, path="/1/2/"),
    ]

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.UserDepartmentDao.aget_user_departments",
            new=AsyncMock(return_value=[_user_department(1)]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_active_by_tenant",
            new=AsyncMock(return_value=departments),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_department_ids",
            new=AsyncMock(return_value=[_binding(2, 100)]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.get_async_db_session",
            return_value=mock_session,
        ),
    ):
        result = await svc.get_my_department_tree_for_create(exclude_space_id=100)

    assert result["bound_department_ids"] == []


@pytest.mark.asyncio
async def test_exclude_space_id_keeps_other_bindings(mock_session) -> None:
    login_user = _login_user()
    svc = KnowledgeSpaceService(request=None, login_user=login_user)

    departments = [
        _department(1, name="研发部", path="/1/"),
        _department(2, name="前端组", parent_id=1, path="/1/2/"),
    ]

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.UserDepartmentDao.aget_user_departments",
            new=AsyncMock(return_value=[_user_department(1)]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_active_by_tenant",
            new=AsyncMock(return_value=departments),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_department_ids",
            new=AsyncMock(return_value=[_binding(2, 100), _binding(2, 101)]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.get_async_db_session",
            return_value=mock_session,
        ),
    ):
        result = await svc.get_my_department_tree_for_create(exclude_space_id=100)

    assert result["bound_department_ids"] == [2]
