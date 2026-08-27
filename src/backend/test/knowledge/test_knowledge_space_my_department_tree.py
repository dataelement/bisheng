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
    org_level: str | None = None,
):
    return SimpleNamespace(
        id=dept_id,
        dept_id=dept_external_id or f"BS@{dept_id}",
        name=name,
        parent_id=parent_id,
        path=path or f"/{dept_id}/",
        sort_order=sort_order,
        status="active",
        org_level=org_level,
        short_name=None,
    )


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


@pytest.fixture(autouse=True)
def mock_department_admin_grants():
    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service."
        "DepartmentAdminGrantDao.aget_department_ids_by_user_id",
        new=AsyncMock(return_value=[]),
    ):
        yield


def _tree_ids(nodes: list) -> set[int]:
    ids: set[int] = set()
    for node in nodes:
        ids.add(int(node["id"]))
        ids |= _tree_ids(node.get("children") or [])
    return ids


def _find_node(nodes: list, dept_id: int):
    for node in nodes:
        if int(node["id"]) == dept_id:
            return node
        found = _find_node(node.get("children") or [], dept_id)
        if found is not None:
            return found
    return None


@pytest.mark.asyncio
async def test_admin_tree_truncates_at_office_and_drops_unlabeled(mock_session) -> None:
    login_user = _login_user(is_admin=True)
    svc = KnowledgeSpaceService(request=None, login_user=login_user)

    departments = [
        _department(1, name="公司", path="/1/", org_level="company"),
        _department(2, name="炼铁部", parent_id=1, path="/1/2/", org_level="dept"),
        _department(3, name="炼铁作业区", parent_id=2, path="/1/2/3/", org_level="office"),
        _department(4, name="班组", parent_id=3, path="/1/2/3/4/", org_level="squad"),
        _department(5, name="未打标", parent_id=2, path="/1/2/5/", org_level=None),
        _department(6, name="市场部", path="/6/", org_level="dept"),
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
    assert _tree_ids(result["data"]) == {1, 2, 3, 6}
    office = _find_node(result["data"], 3)
    assert office["org_level"] == "office"
    assert office["children"] == []


@pytest.mark.asyncio
async def test_empty_when_user_has_no_admin_grants(mock_session) -> None:
    login_user = _login_user()
    svc = KnowledgeSpaceService(request=None, login_user=login_user)

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_active_by_tenant",
            new=AsyncMock(return_value=[_department(1, name="公司", org_level="company")]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.get_async_db_session",
            return_value=mock_session,
        ),
    ):
        result = await svc.get_my_department_tree_for_create()

    assert result == {"data": [], "bound_department_ids": []}


@pytest.mark.asyncio
async def test_membership_does_not_expand_clinic_tree(mock_session) -> None:
    login_user = _login_user()
    svc = KnowledgeSpaceService(request=None, login_user=login_user)

    departments = [
        _department(1, name="炼铁部", path="/1/", org_level="dept"),
        _department(2, name="炼铁作业区", parent_id=1, path="/1/2/", org_level="office"),
        _department(3, name="设备处", path="/3/", org_level="dept"),
        _department(4, name="设备检修室", parent_id=3, path="/3/4/", org_level="office"),
    ]

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.UserDepartmentDao.aget_user_departments",
            new=AsyncMock(return_value=[SimpleNamespace(department_id=1)]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "DepartmentAdminGrantDao.aget_department_ids_by_user_id",
            new=AsyncMock(return_value=[3]),
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

    assert _tree_ids(result["data"]) == {3, 4}


@pytest.mark.asyncio
async def test_multiple_dept_admin_grants_are_unioned(mock_session) -> None:
    login_user = _login_user()
    svc = KnowledgeSpaceService(request=None, login_user=login_user)

    departments = [
        _department(1, name="炼铁部", path="/1/", org_level="dept"),
        _department(2, name="炼铁作业区", parent_id=1, path="/1/2/", org_level="office"),
        _department(3, name="设备处", path="/3/", org_level="dept"),
        _department(4, name="设备检修室", parent_id=3, path="/3/4/", org_level="office"),
        _department(5, name="无关科室", path="/5/", org_level="office"),
    ]

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "DepartmentAdminGrantDao.aget_department_ids_by_user_id",
            new=AsyncMock(return_value=[1, 3]),
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

    assert _tree_ids(result["data"]) == {1, 2, 3, 4}


@pytest.mark.asyncio
async def test_squad_only_admin_grant_returns_empty_tree(mock_session) -> None:
    login_user = _login_user()
    svc = KnowledgeSpaceService(request=None, login_user=login_user)

    departments = [
        _department(3, name="科室", path="/1/2/3/", org_level="office"),
        _department(4, name="班组", parent_id=3, path="/1/2/3/4/", org_level="squad"),
    ]

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "DepartmentAdminGrantDao.aget_department_ids_by_user_id",
            new=AsyncMock(return_value=[4]),
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

    assert result == {"data": [], "bound_department_ids": []}


@pytest.mark.asyncio
async def test_marks_bound_offices(mock_session) -> None:
    login_user = _login_user()
    svc = KnowledgeSpaceService(request=None, login_user=login_user)

    departments = [
        _department(1, name="炼铁部", path="/1/", org_level="dept"),
        _department(2, name="炼铁作业区", parent_id=1, path="/1/2/", org_level="office"),
    ]

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "DepartmentAdminGrantDao.aget_department_ids_by_user_id",
            new=AsyncMock(return_value=[1]),
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
async def test_does_not_mark_bound_non_office_nodes(mock_session) -> None:
    login_user = _login_user()
    svc = KnowledgeSpaceService(request=None, login_user=login_user)
    bindings_mock = AsyncMock(return_value=[_binding(1, 200)])

    departments = [
        _department(1, name="炼铁部", path="/1/", org_level="dept"),
        _department(2, name="炼铁作业区", parent_id=1, path="/1/2/", org_level="office"),
    ]

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "DepartmentAdminGrantDao.aget_department_ids_by_user_id",
            new=AsyncMock(return_value=[1]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_active_by_tenant",
            new=AsyncMock(return_value=departments),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_department_ids",
            bindings_mock,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.get_async_db_session",
            return_value=mock_session,
        ),
    ):
        result = await svc.get_my_department_tree_for_create()

    assert result["bound_department_ids"] == []
    bindings_mock.assert_awaited_once()
    queried_ids = set(bindings_mock.await_args.args[0])
    assert queried_ids == {2}


@pytest.mark.asyncio
async def test_exclude_space_id_omits_current_binding(mock_session) -> None:
    login_user = _login_user()
    svc = KnowledgeSpaceService(request=None, login_user=login_user)

    departments = [
        _department(1, name="炼铁部", path="/1/", org_level="dept"),
        _department(2, name="炼铁作业区", parent_id=1, path="/1/2/", org_level="office"),
    ]

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "DepartmentAdminGrantDao.aget_department_ids_by_user_id",
            new=AsyncMock(return_value=[1]),
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
        _department(1, name="炼铁部", path="/1/", org_level="dept"),
        _department(2, name="炼铁作业区", parent_id=1, path="/1/2/", org_level="office"),
    ]

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "DepartmentAdminGrantDao.aget_department_ids_by_user_id",
            new=AsyncMock(return_value=[1]),
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
