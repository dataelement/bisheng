"""Knowledge creation permission context and candidate API contracts."""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.common.errcode.knowledge_space import SpaceLimitError
from bisheng.knowledge.api.endpoints import knowledge_space as endpoints
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


class _Prospective:
    def __init__(self) -> None:
        self.calls = []

    async def get_context(self, **kwargs):
        self.calls.append(("context", kwargs))
        return {"catalog_release_id": 42, "can_configure_initial_permissions": True, "grantable_models": []}

    async def list_users(self, **kwargs):
        self.calls.append(("users", kwargs))
        return {"data": [], "total": 0}

    async def list_user_groups(self, **kwargs):
        self.calls.append(("groups", kwargs))
        return {"data": [], "total": 0}

    async def list_department_children(self, **kwargs):
        self.calls.append(("children", kwargs))
        return []

    async def search_departments(self, **kwargs):
        self.calls.append(("search", kwargs))
        return {"roots": [], "total_matches": 0, "truncated": False}

    async def get_department_path(self, **kwargs):
        self.calls.append(("path", kwargs))
        return {"roots": [], "total_matches": 0, "truncated": False}


def _service(prospective: _Prospective) -> KnowledgeSpaceService:
    service = KnowledgeSpaceService(
        request=MagicMock(),
        login_user=SimpleNamespace(user_id=11, tenant_id=7, is_admin=lambda: False),
        prospective_grant_application=prospective,
    )
    service._permission_actor = AsyncMock(return_value=SimpleNamespace(user_id=11, current_tenant_id=7))
    return service


async def test_creation_context_and_candidates_use_server_tenant_and_same_shape() -> None:
    prospective = _Prospective()
    service = _service(prospective)
    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.QuotaService.get_effective_quota",
            new=AsyncMock(return_value=50),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_count_spaces_by_user",
            new=AsyncMock(return_value=0),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.LLMService.get_workbench_llm",
            new=AsyncMock(return_value=SimpleNamespace(embedding_model=SimpleNamespace(id=3))),
        ),
    ):
        context = await service.get_creation_permission_context()
        users = await service.list_creation_grant_users(keyword="A", page=2, page_size=25)
        await service.list_creation_grant_user_groups(keyword="G", page=1, page_size=20)
        await service.list_creation_grant_department_children(parent_id=5)
        await service.search_creation_grant_departments(keyword="R", limit=10)
        await service.get_creation_grant_department_path(9)

    assert context["catalog_release_id"] == 42
    assert users == {"data": [], "total": 0}
    assert [name for name, _ in prospective.calls] == [
        "context",
        "users",
        "groups",
        "children",
        "search",
        "path",
    ]
    assert all(call["tenant_id"] == 7 for _, call in prospective.calls)
    assert all(call["resource_type"] == "knowledge_space" for _, call in prospective.calls)


async def test_creation_qualification_fails_closed_before_permission_directory() -> None:
    prospective = _Prospective()
    service = _service(prospective)
    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.QuotaService.get_effective_quota",
            new=AsyncMock(return_value=30),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_count_spaces_by_user",
            new=AsyncMock(return_value=30),
        ),
    ):
        with pytest.raises(SpaceLimitError):
            await service.get_creation_permission_context()

    assert prospective.calls == []


def test_creation_routes_exist_and_do_not_accept_tenant_id() -> None:
    paths = {route.path for route in endpoints.router.routes}
    assert {
        "/knowledge/space/creation-permission-context",
        "/knowledge/space/creation-grant-subjects/users",
        "/knowledge/space/creation-grant-subjects/user-groups",
        "/knowledge/space/creation-grant-subjects/departments/children",
        "/knowledge/space/creation-grant-subjects/departments/search",
        "/knowledge/space/creation-grant-subjects/departments/{department_id}/path-tree",
    } <= paths
    for endpoint in (
        endpoints.get_creation_permission_context,
        endpoints.list_creation_grant_users,
        endpoints.list_creation_grant_user_groups,
        endpoints.list_creation_grant_department_children,
        endpoints.search_creation_grant_departments,
        endpoints.get_creation_grant_department_path,
    ):
        assert "tenant_id" not in inspect.signature(endpoint).parameters
