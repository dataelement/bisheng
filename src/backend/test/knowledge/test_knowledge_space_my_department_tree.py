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
async def test_squad_admin_grant_shows_nearest_office(mock_session) -> None:
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

    assert _tree_ids(result["data"]) == {3}
    assert result["bound_department_ids"] == []


@pytest.mark.parametrize(
    "grants,expected_ids",
    [
        ([2, 9], {2, 3, 6, 8}),
        ([4, 5], {3}),
        ([4, 9, 10], {3, 8}),
        ([2, 3, 4], {2, 3, 6}),
    ],
)
async def test_mixed_admin_grants_union_subtrees_and_nearest_offices(mock_session, grants, expected_ids) -> None:
    svc = KnowledgeSpaceService(request=None, login_user=_login_user())
    departments = [
        _department(1, name="公司", path="/1/", org_level="company"),
        _department(2, name="制造部", parent_id=1, path="/1/2/", org_level="dept"),
        _department(3, name="制造室", parent_id=2, path="/1/2/3/", org_level="office"),
        _department(4, name="制造班组", parent_id=3, path="/1/2/3/4/", org_level="squad"),
        _department(5, name="班组下级", parent_id=4, path="/1/2/3/4/5/"),
        _department(6, name="制造兄弟科室", parent_id=2, path="/1/2/6/", org_level="office"),
        _department(7, name="设备部", parent_id=1, path="/1/7/", org_level="dept"),
        _department(8, name="检修室", parent_id=7, path="/1/7/8/", org_level="office"),
        _department(9, name="检修班组", parent_id=8, path="/1/7/8/9/", org_level="squad"),
        _department(10, name="检修下级", parent_id=9, path="/1/7/8/9/10/"),
    ]
    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "DepartmentAdminGrantDao.aget_department_ids_by_user_id",
            new=AsyncMock(return_value=grants),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_active_by_tenant",
            new=AsyncMock(return_value=departments),
        ) as active_departments,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_department_ids",
            new=AsyncMock(return_value=[_binding(8, 100)]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.get_async_db_session",
            return_value=mock_session,
        ),
    ):
        result = await svc.get_my_department_tree_for_create()

    active_departments.assert_awaited_once_with(1)
    assert _tree_ids(result["data"]) == expected_ids
    assert result["bound_department_ids"] == ([8] if 8 in expected_ids else [])

    # 检查节点总数以确认没有重复节点。
    def count_nodes(nodes):
        return sum(1 + count_nodes(node["children"]) for node in nodes)

    assert count_nodes(result["data"]) == len(expected_ids)


@pytest.mark.parametrize("invalid_parent", ["missing", "cycle", "archived", "deleted", "descendant_office"])
async def test_lower_org_with_invalid_parent_chain_does_not_gain_office(mock_session, invalid_parent) -> None:
    svc = KnowledgeSpaceService(request=None, login_user=_login_user())
    office = _department(3, name="不可选科室", org_level="office")
    squad = _department(4, name="班组", parent_id=3, org_level="squad")
    if invalid_parent == "missing":
        squad.parent_id = 999
    elif invalid_parent == "cycle":
        squad.parent_id = 5
    elif invalid_parent == "archived":
        office.status = "archived"
    elif invalid_parent == "deleted":
        office.is_deleted = 1
    else:
        squad.parent_id = 999
    departments = [office, squad, _department(5, name="下级", parent_id=4)]
    if invalid_parent == "descendant_office":
        departments.append(_department(6, name="下级误标科室", parent_id=4, path="/4/6/", org_level="office"))
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
            "bisheng.knowledge.domain.services.knowledge_space_service.get_async_db_session",
            return_value=mock_session,
        ),
    ):
        result = await svc.get_my_department_tree_for_create()
    assert result == {"data": [], "bound_department_ids": []}


async def test_http_tree_and_create_validation_share_nearest_office_scope(mock_session, monkeypatch) -> None:
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from httpx import ASGITransport, AsyncClient

    from bisheng.approval.api.endpoints import shougang_approval as approval_endpoint
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.common.errcode.base import BaseErrorCode
    from bisheng.common.errcode.knowledge_space import SpaceCreateDepartmentDeniedError
    from bisheng.knowledge.api.endpoints import knowledge_space as space_endpoint
    from bisheng.knowledge.domain.services import knowledge_space_service as space_module

    login_user = _login_user()
    svc = KnowledgeSpaceService(request=None, login_user=login_user)
    departments = [
        _department(3, name="最近科室", path="/1/3/", org_level="office"),
        _department(4, name="班组", parent_id=3, path="/1/3/4/", org_level="squad"),
        _department(6, name="兄弟科室", path="/1/6/", org_level="office"),
    ]
    monkeypatch.setattr(space_module.DepartmentDao, "aget_active_by_tenant", AsyncMock(return_value=departments))
    monkeypatch.setattr(
        space_module.DepartmentDao,
        "aget_by_id",
        AsyncMock(side_effect=lambda did: next((dept for dept in departments if dept.id == did), None)),
    )
    monkeypatch.setattr(
        space_module.DepartmentAdminGrantDao, "aget_department_ids_by_user_id", AsyncMock(return_value=[4])
    )
    monkeypatch.setattr(space_module.DepartmentKnowledgeSpaceDao, "aget_by_department_ids", AsyncMock(return_value=[]))
    monkeypatch.setattr(space_module, "get_async_db_session", lambda: mock_session)
    monkeypatch.setattr(
        space_module.LLMService,
        "get_workbench_llm",
        AsyncMock(return_value=SimpleNamespace(embedding_model=SimpleNamespace(id="test"))),
    )
    monkeypatch.setattr(svc, "_ensure_space_name_unique_in_scope", AsyncMock())
    app = FastAPI()
    app.add_api_route(
        "/api/v1/knowledge/space/create-options/my-department-tree",
        space_endpoint.get_create_option_my_department_tree,
        methods=["GET"],
    )
    app.add_api_route(
        "/api/v1/approval/shougang/knowledge-space-create/validate",
        approval_endpoint.validate_knowledge_space_create,
        methods=["POST"],
    )
    app.dependency_overrides[space_endpoint.get_knowledge_space_service] = lambda: svc
    app.dependency_overrides[approval_endpoint.get_knowledge_space_service] = lambda: svc
    app.dependency_overrides[UserPayload.get_login_user] = lambda: login_user

    @app.exception_handler(BaseErrorCode)
    async def business_error(_request, exc):
        return JSONResponse({"status_code": exc.code, "status_message": exc.message, "data": None})

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        tree = await client.get("/api/v1/knowledge/space/create-options/my-department-tree")
        assert tree.status_code == 200 and tree.json()["status_code"] == 200
        assert _tree_ids(tree.json()["data"]["data"]) == {3}
        payload = {"name": "最近科室库", "space_level": "department", "department_id": 3, "is_clinic": True}
        accepted = await client.post("/api/v1/approval/shougang/knowledge-space-create/validate", json=payload)
        assert accepted.status_code == 200 and accepted.json()["status_code"] == 200
        assert accepted.json()["data"] == {"approval_required": False}
        rejected = await client.post(
            "/api/v1/approval/shougang/knowledge-space-create/validate", json={**payload, "department_id": 6}
        )
        assert rejected.json()["status_code"] == SpaceCreateDepartmentDeniedError.Code


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
