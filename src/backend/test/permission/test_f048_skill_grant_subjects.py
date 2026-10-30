"""Skill permission pickers must authorize the resource and use its tenant."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.permission.api.endpoints import grant_subjects
from bisheng.permission.domain.services.grant_subject_service import GrantSubjectScope

PICKERS = [
    (
        "users?keyword=alice&page=2&page_size=10",
        "list_candidate_users",
        {"keyword": "alice", "page": 2, "page_size": 10},
        [],
    ),
    (
        "user-groups?keyword=team&page=2&page_size=10",
        "list_candidate_user_groups",
        {"keyword": "team", "page": 2, "page_size": 10},
        [],
    ),
    ("departments/children?parent_id=7", "list_candidate_department_layer", {"parent_id": 7}, []),
    (
        "departments/search?keyword=team&limit=10",
        "search_candidate_departments",
        {"keyword": "team", "limit": 10},
        {"roots": []},
    ),
    ("departments/7/path-tree", "get_candidate_department_path", {"dept_id": 7}, {"roots": []}),
]


@pytest.fixture()
async def picker(monkeypatch):
    login_user = SimpleNamespace(tenant_id=99)
    actor = SimpleNamespace(tenant_id=99)
    registry = SimpleNamespace(resolve=AsyncMock(return_value=SimpleNamespace(tenant_id=42)))
    monkeypatch.setattr(grant_subjects, "resolve_permission_actor", AsyncMock(return_value=actor))
    monkeypatch.setattr(grant_subjects, "get_f048_resource_registry", AsyncMock(return_value=registry))
    check = AsyncMock(return_value=True)
    monkeypatch.setattr(grant_subjects, "check_business_action", check)
    counts = [AsyncMock(return_value=0), AsyncMock(return_value=0)]
    for name, count in zip(("count_candidate_users", "count_candidate_user_groups"), counts, strict=True):
        monkeypatch.setattr(grant_subjects.grant_subject_service, name, count)
    app = FastAPI()
    app.include_router(grant_subjects.router, prefix="/api/v1/permissions")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: login_user
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield SimpleNamespace(
            client=client, user=login_user, actor=actor, registry=registry, check=check, counts=counts
        )


@pytest.mark.parametrize(("path", "service_name", "kwargs", "result"), PICKERS)
async def test_skill_picker_authorizes_and_passes_resource_tenant(
    picker, monkeypatch, path, service_name, kwargs, result
):
    service = AsyncMock(return_value=result)
    monkeypatch.setattr(grant_subjects.grant_subject_service, service_name, service)

    response = await picker.client.get(f"/api/v1/permissions/resources/linsight_skill/5/grant-subjects/{path}")

    assert response.status_code == 200
    assert response.json()["status_code"] == 200
    picker.registry.resolve.assert_awaited_once_with(
        resource_type="linsight_skill", resource_id="5", actor=picker.actor, action="manage_permission"
    )
    picker.check.assert_awaited_once_with(
        picker.user, resource_type="linsight_skill", resource_id="5", action="manage_permission"
    )
    service.assert_awaited_once_with(GrantSubjectScope(tenant_id=42, department_path=None), **kwargs)


@pytest.mark.parametrize(("path", "service_name", "kwargs", "result"), PICKERS)
@pytest.mark.parametrize("denial", ["no_manage_permission", "invalid_target", "unknown_type"])
async def test_skill_picker_denials_do_not_query_candidates(
    picker, monkeypatch, path, service_name, kwargs, result, denial
):
    service = AsyncMock(return_value=result)
    monkeypatch.setattr(grant_subjects.grant_subject_service, service_name, service)
    resource_type = "linsight_skill"
    if denial == "no_manage_permission":
        picker.check.return_value = False
    elif denial == "invalid_target":
        picker.registry.resolve.side_effect = PermissionDeniedError()
    else:
        resource_type = "not_a_resource"

    response = await picker.client.get(f"/api/v1/permissions/resources/{resource_type}/5/grant-subjects/{path}")

    assert response.status_code == 200
    assert response.json()["status_code"] == 19000
    service.assert_not_awaited()
    for count in picker.counts:
        count.assert_not_awaited()
    if denial != "no_manage_permission":
        picker.check.assert_not_awaited()
    if denial == "unknown_type":
        picker.registry.resolve.assert_not_awaited()
