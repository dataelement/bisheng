"""knowledge:write also satisfies knowledge:read; no other scope is implied."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from bisheng.common.errcode.open_api import PersonalTokenDataScopeError
from bisheng.knowledge.domain.services import knowledge_permission_service
from bisheng.knowledge.domain.services.knowledge_file_service import KnowledgeFileService
from bisheng.knowledge.domain.services.knowledge_metadata_service import KnowledgeMetadataService
from bisheng.open_api.domain.scopes import (
    OPEN_API_SCOPE_MAP,
    OPEN_API_SCOPES,
    get_open_api_scope_marker,
    is_scope_granted,
)
from bisheng.open_endpoints.api.endpoints import knowledge as knowledge_endpoints
from test.open_api.test_dependencies import build_app, request, service_account_principal


def _validate_with(monkeypatch, scopes):
    async def validate(_authorization):
        return service_account_principal(scopes=frozenset(scopes))

    monkeypatch.setattr("bisheng.open_api.api.dependencies.validate_bearer", validate)


async def test_write_only_key_can_call_read_endpoint(monkeypatch):
    _validate_with(monkeypatch, {"knowledge:write"})

    response = await request(build_app(), "/api/v2/registered", authorization="Bearer opaque")

    assert response.status_code == 200


async def test_read_only_key_still_cannot_call_write_endpoint(monkeypatch):
    _validate_with(monkeypatch, {"knowledge:read"})

    async with AsyncClient(transport=ASGITransport(app=build_app()), base_url="http://test") as client:
        response = await client.post(
            "/api/v2/upload",
            headers={"Authorization": "Bearer opaque"},
            files={"file": ("a.txt", b"x")},
        )

    assert response.status_code == 403
    body = response.json()
    assert body["status_code"] == 26003
    assert body["data"]["required"] == "knowledge:write"


async def test_key_without_knowledge_scope_reports_read_as_required(monkeypatch):
    _validate_with(monkeypatch, {"chat:invoke"})

    response = await request(build_app(), "/api/v2/registered", authorization="Bearer opaque")

    assert response.status_code == 403
    assert response.json()["status_code"] == 26003
    assert response.json()["data"]["required"] == "knowledge:read"


def test_implication_does_not_change_listed_scopes():
    principal = service_account_principal(scopes=frozenset({"knowledge:write"}))

    assert principal.has_scope("knowledge:read")
    # whoami returns sorted(principal.scopes): the implied scope must not appear there.
    assert sorted(principal.scopes) == ["knowledge:write"]


@pytest.mark.parametrize("required", sorted(scope.code for scope in OPEN_API_SCOPES if scope.code != "knowledge:read"))
def test_knowledge_write_implies_nothing_else(required):
    if required == "knowledge:write":
        assert is_scope_granted(required, frozenset({"knowledge:write"}))
    else:
        assert not is_scope_granted(required, frozenset({"knowledge:write"}))
        assert not is_scope_granted(required, frozenset({"knowledge:read"}))


@pytest.mark.parametrize(
    ("endpoint", "method", "path"),
    [
        (knowledge_endpoints.list_metadata_fields, "GET", "/api/v2/knowledge/get_metadata_fields/{knowledge_id}"),
        (knowledge_endpoints.list_file_user_metadata, "POST", "/api/v2/knowledge/file/list_user_metadata"),
    ],
)
def test_metadata_read_endpoints_require_knowledge_read(endpoint, method, path):
    assert get_open_api_scope_marker(endpoint).scope == "knowledge:read"
    assert (method, path) in OPEN_API_SCOPE_MAP["knowledge:read"].endpoints
    assert (method, path) not in OPEN_API_SCOPE_MAP["knowledge:write"].endpoints


# Personal tokens hold knowledge:read, so they now reach the two metadata read
# endpoints. Both check the library through check_business_action, which raises
# the F066 data-scope denial (26044) for a library the holder did not create.


async def test_metadata_read_endpoints_keep_personal_token_data_scope(monkeypatch):
    denied = AsyncMock(side_effect=PersonalTokenDataScopeError())
    monkeypatch.setattr(knowledge_permission_service, "check_business_action", denied)
    knowledge = SimpleNamespace(id=23, user_id=99, metadata_fields=[])
    knowledge_repo = SimpleNamespace(find_by_id=AsyncMock(return_value=knowledge))
    file_repo = SimpleNamespace(get_user_metadata_by_knowledge_file_ids=AsyncMock())
    user = SimpleNamespace(user_id=5)

    metadata_service = KnowledgeMetadataService(
        knowledge_repository=knowledge_repo,
        knowledge_file_repository=file_repo,
        permission_service=knowledge_permission_service.KnowledgePermissionService(),
    )
    with pytest.raises(PersonalTokenDataScopeError):
        await metadata_service.list_metadata_fields(user, 23)

    file_service = KnowledgeFileService(knowledge_file_repository=file_repo, knowledge_repository=knowledge_repo)
    with pytest.raises(PersonalTokenDataScopeError):
        await file_service.list_knowledge_file_user_metadata(user, 23, [1])
    file_repo.get_user_metadata_by_knowledge_file_ids.assert_not_awaited()
