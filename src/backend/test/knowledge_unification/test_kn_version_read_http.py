"""The actual version DI and routers consume native, visible read facts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.requests import Request

from bisheng.common.dependencies.core_deps import get_db_session
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.core.context.tenant import management_tenant_scope
from bisheng.knowledge.api import dependencies
from bisheng.knowledge.api.endpoints import knowledge_version as api
from bisheng.knowledge.domain.repositories import knowledge_version_read_repository as repository_module
from bisheng.knowledge.domain.services import knowledge_version_read_service as service_module
from bisheng.permission.application.identity import reset_current_permission_actor, set_current_permission_actor
from test.knowledge_unification import test_kn_version_read as fixtures

catalog, concrete_tenant = fixtures.catalog, fixtures.concrete_tenant
identity, reads = fixtures.identity, fixtures.reads
chain, space = fixtures.chain, fixtures.space


@pytest.fixture
async def http(reads, monkeypatch):
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")

    @app.exception_handler(BaseErrorCode)
    async def business_error(_request, error):
        return JSONResponse(content=jsonable_encoder(error.return_resp_instance()))

    async def unused_legacy_session():
        # An actual unbound Session proves these reads never query legacy repositories.
        async with AsyncSession() as session:
            yield session

    app.dependency_overrides[UserPayload.get_login_user] = lambda: reads.user
    app.dependency_overrides[get_db_session] = unused_legacy_session
    monkeypatch.setattr(repository_module, "get_async_db_session", reads.catalog.sessions)
    monkeypatch.setattr(service_module, "get_f048_resource_adapter", AsyncMock(return_value=reads.adapter))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://offline") as client:
        yield SimpleNamespace(client=client, app=app, reads=reads)


async def test_actual_dependency_builds_the_shared_read_port_without_querying_legacy_repositories(http):
    assert hasattr(dependencies, "get_knowledge_version_read_service")
    factory = dependencies.get_knowledge_version_read_service
    request = Request({"type": "http", "headers": []})
    read = await factory(request=request, login_user=http.reads.user)
    old = await dependencies.get_knowledge_version_service(
        request=request,
        login_user=http.reads.user,
        doc_repo=None,
        version_repo=None,
        knowledge_file_repo=None,
        read_service=read,
    )
    assert old._reads() is read
    assert read.login_user is http.reads.user
    assert http.reads.catalog.facts.sql == []


async def test_history_http_is_visible_only_and_does_not_require_primary_or_root_visibility(http):
    await http.reads.catalog.seed([space(), *chain(1, 2)])
    http.reads.facts.allowed.add(10001)
    response = await http.client.get("/api/v1/knowledge/space/file/10001/versions")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["title"] == "file 1 v1.md" and data["current_primary_version_no"] is None
    assert [entry["knowledge_file_id"] for entry in data["versions"]] == [10001]
    assert "owner 10002" not in response.text
    assert all(key[1] == "knowledge_file" for batch in http.reads.facts.snapshots for key in batch)


async def test_history_http_preserves_missing_chain_404_and_permission_denial(http):
    response = await http.client.get("/api/v1/knowledge/space/file/999/versions")
    assert response.status_code == 404 and response.json()["detail"] == "version chain not found for this file"
    await http.reads.catalog.seed([space(), *chain(1)])
    response = await http.client.get("/api/v1/knowledge/space/file/10001/versions")
    assert response.status_code == 200
    assert response.json()["status_code"] == 19000


@pytest.mark.parametrize("kind", ["search-page", "version-search-page"])
async def test_new_http_cursor_pages_do_not_skip_prechecked_rows(http, kind):
    await http.reads.catalog.seed([space(), *chain(1), *chain(2), *chain(3, 2), *chain(4)])
    http.reads.facts.allowed.update({10001, 20001, 30002, 40001})
    url = f"/api/v1/knowledge/space/10/document/{kind}"
    ids, cursor = [], None
    while True:
        params = {"current_file_id": 10001, "page_size": 1}
        if cursor is not None:
            params["cursor"] = cursor
        response = await http.client.get(url, params=params)
        assert response.status_code == 200
        data = response.json()["data"]
        assert set(data) == {"data", "page_size", "has_more", "next_cursor"}
        ids.extend(item["document_id"] for item in data["data"])
        if not data["has_more"]:
            assert data["next_cursor"] is None
            break
        assert data["next_cursor"] != cursor
        cursor = data["next_cursor"]
    assert ids == ([2, 4] if kind == "version-search-page" else [2, 3, 4])


@pytest.mark.parametrize("kind", ["search", "version-search"])
async def test_legacy_http_arrays_are_complete_beyond_the_new_page_scan_budget(http, kind):
    await http.reads.catalog.seed([space(), *[item for ident in range(1, 1103) for item in chain(ident)]])
    http.reads.facts.allowed.update({10001, 11020001})
    response = await http.client.get(
        f"/api/v1/knowledge/space/10/document/{kind}", params={"current_file_id": 10001, "keyword": "file"}
    )
    assert response.status_code == 200
    assert isinstance(response.json()["data"], list)
    assert [item["document_id"] for item in response.json()["data"]] == [1102]
    assert max(map(len, http.reads.facts.checked)) <= 100


async def test_http_cursor_context_mismatch_uses_the_existing_business_error(http):
    await http.reads.catalog.seed([space(), *chain(1), *chain(2), *chain(3)])
    http.reads.facts.allowed.update({10001, 20001, 30001})
    url = "/api/v1/knowledge/space/10/document/search-page"
    first = await http.client.get(url, params={"current_file_id": 10001, "page_size": 1})
    assert first.status_code == 200
    cursor = first.json()["data"]["next_cursor"]
    assert cursor
    response = await http.client.get(
        url, params={"current_file_id": 10001, "page_size": 1, "keyword": "other", "cursor": cursor}
    )
    assert response.status_code == 200 and response.json()["status_code"] == 18070


async def test_http_foreign_and_invisible_candidates_never_leak_metadata(http):
    await http.reads.catalog.seed([space(), space(20, 202), *chain(1), *chain(2), *chain(3, space_id=20, tenant=202)])
    http.reads.facts.allowed.update({10001, 30001})
    response = await http.client.get(
        "/api/v1/knowledge/space/10/document/search-page", params={"current_file_id": 10001}
    )
    assert response.status_code == 200 and response.json()["data"]["data"] == []
    assert "owner 20001" not in response.text and "owner 30001" not in response.text


@pytest.mark.parametrize(
    "query",
    [
        {"page_size": 0},
        {"page_size": 201},
        {"page_size": True},
        {"current_file_id": 0},
        {"current_file_id": 9007199254740992},
    ],
)
async def test_new_http_bounds_fail_before_database_or_permission_io(http, query):
    response = await http.client.get(
        "/api/v1/knowledge/space/10/document/search-page", params={"current_file_id": 10001, **query}
    )
    assert response.status_code == 422
    assert http.reads.catalog.facts.sql == [] and http.reads.facts.checked == []


async def test_real_di_keeps_home_identity_for_a_trusted_selected_management_tenant(http):
    await http.reads.catalog.seed([space(), *chain(1)])
    user = UserPayload(user_id=7, tenant_id=1, user_role=[], is_global_super=True)
    http.app.dependency_overrides[UserPayload.get_login_user] = lambda: user
    token = set_current_permission_actor(None)
    try:
        with management_tenant_scope(101):
            response = await http.client.get("/api/v1/knowledge/space/file/10001/versions")
        assert response.status_code == 200 and len(response.json()["data"]["versions"]) == 1
        assert user.tenant_id == 1
    finally:
        reset_current_permission_actor(token)


async def test_history_can_be_read_while_the_feature_switch_and_all_writes_remain_unopened(http, monkeypatch):
    await http.reads.catalog.seed([space(), *chain(1)])
    http.reads.facts.allowed.add(10001)
    from bisheng.knowledge.domain.services import knowledge_version_service as original

    monkeypatch.setattr(
        original,
        "bisheng_settings",
        SimpleNamespace(
            async_get_knowledge=AsyncMock(side_effect=AssertionError("history must not read the write feature gate")),
        ),
    )
    response = await http.client.get("/api/v1/knowledge/space/file/10001/versions")
    assert response.status_code == 200 and len(response.json()["data"]["versions"]) == 1
