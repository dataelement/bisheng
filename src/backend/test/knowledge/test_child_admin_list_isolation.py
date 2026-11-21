"""Browser admission and real SQL regressions for child-tenant knowledge lists."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from bisheng.admin.application import request_admission
from bisheng.common.cursor import decode_cursor
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.request_scope import RequestScope, ScopedAPIRouter, inherit_scope
from bisheng.core.context.tenant import get_admin_scope_tenant_id, get_visible_tenant_ids
from bisheng.knowledge.api.endpoints import knowledge_space
from bisheng.knowledge.domain.models import knowledge as knowledge_model
from bisheng.knowledge.domain.services import knowledge_service
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from test.knowledge_unification import test_kn_list as listing_tests

catalog = listing_tests.catalog
concrete_tenant = listing_tests.concrete_tenant
row = listing_tests.row


@pytest.fixture
async def browser_lists(catalog, monkeypatch):
    rows = [row(11), row(12, tenant=1), row(13, tenant=202)] + [
        row(ident, kind=1, tenant=tenant, name=f"qa {ident}")
        for ident, tenant in ((21, 101), (22, 1), (23, 202), (24, 101))
    ]
    for item in rows:
        item.create_time = datetime(2026, 11, 6)
    await catalog.seed(rows)
    user = UserPayload(user_id=7, tenant_id=101, user_role=[], is_global_super=False)
    actor = PermissionActor(user_id=7, current_tenant_id=101, tenant_admin_tenant_ids=frozenset({101}))
    catalog.service.login_user = user
    catalog.service._permission_actor = AsyncMock(side_effect=lambda: actor)
    monkeypatch.setattr(request_admission, "authenticate_browser", AsyncMock(return_value=user))
    monkeypatch.setattr(knowledge_service, "resolve_permission_actor", AsyncMock(side_effect=lambda _: actor))
    monkeypatch.setattr(knowledge_model, "get_async_db_session", catalog.repository._session_factory)
    monkeypatch.setattr(
        knowledge_model,
        "get_database_connection",
        AsyncMock(return_value=SimpleNamespace(async_engine=SimpleNamespace(dialect=SimpleNamespace(name="sqlite")))),
    )
    # SQLite lacks the production name collation and datetime implicit cast.
    monkeypatch.setattr(
        knowledge_model,
        "name_sort_clauses",
        lambda _: [knowledge_model.Knowledge.name.asc(), knowledge_model.Knowledge.id.asc()],
    )

    def sqlite_decode(*args, **kwargs):
        decoded = decode_cursor(*args, **kwargs)
        if decoded and len(decoded) == 2:
            decoded[0] = datetime.fromisoformat(decoded[0])
        return decoded

    monkeypatch.setattr(knowledge_service, "decode_cursor", sqlite_decode)
    monkeypatch.setattr(knowledge_service.UserDao, "get_user_by_ids", lambda _: [])
    monkeypatch.setattr(
        knowledge_service.KnowledgeFileDao, "async_exists_abnormal_files_batch", AsyncMock(return_value=set())
    )
    runtime = SimpleNamespace(list_visible_objects=AsyncMock(return_value=SimpleNamespace(object_ids=("22",))))
    monkeypatch.setattr(knowledge_service, "get_f048_runtime", AsyncMock(return_value=runtime))
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    router = ScopedAPIRouter()

    @router.get("/knowledge/space/admin/list")
    async def spaces():
        return await knowledge_space.list_admin_spaces(
            keyword=None, page=1, page_size=20, has_abnormal=None, svc=catalog.service
        )

    @router.get("/knowledge")
    async def qa(sort_by: str = "update_time", cursor: str | None = None):
        return await KnowledgeService.get_knowledge(
            None,
            user,
            knowledge_model.KnowledgeTypeEnum.QA,
            sort_by=sort_by,
            page_size=1,
            cursor=cursor,
        )

    @router.get("/scope")
    async def scope():
        return {"pin": get_admin_scope_tenant_id(), "visible": sorted(get_visible_tenant_ids())}

    @app.exception_handler(BaseErrorCode)
    async def business_error(_request, exc):
        return JSONResponse(exc.return_resp_instance().model_dump())

    inherit_scope(router, RequestScope.TENANT)
    app.include_router(router)
    request_admission.install_request_admission(app)
    return SimpleNamespace(app=app, actor=actor, runtime=runtime)


async def test_child_admin_management_list_uses_authenticated_own_tenant(browser_lists):
    before = get_admin_scope_tenant_id()
    async with AsyncClient(transport=ASGITransport(app=browser_lists.app), base_url="http://test") as client:
        response = await client.get("/knowledge/space/admin/list")
    result = response.json()
    assert result["status_code"] == 200, result
    assert result["data"]["total"] == 1
    assert [item["id"] for item in result["data"]["data"]] == [11]
    assert response.headers["X-Management-Tenant"] == "101"
    assert get_admin_scope_tenant_id() == before


@pytest.mark.parametrize("sort_by", ["name", "update_time", "create_time"])
async def test_child_admin_qa_pages_never_include_root_or_other_child(browser_lists, sort_by):
    found, cursor = [], None
    async with AsyncClient(transport=ASGITransport(app=browser_lists.app), base_url="http://test") as client:
        for _ in range(5):
            params = {"sort_by": sort_by}
            if cursor:
                params["cursor"] = cursor
            response = await client.get("/knowledge", params=params)
            page = response.json()
            found.extend(item["id"] for item in page["data"])
            if not page["has_more"]:
                break
            cursor = page["next_cursor"]
    assert sorted(found) == [21, 24]
    browser_lists.runtime.list_visible_objects.assert_not_awaited()


async def test_ordinary_user_retains_authorized_root_sharing_without_admin_list_access(browser_lists):
    object.__setattr__(browser_lists.actor, "tenant_admin_tenant_ids", frozenset())
    async with AsyncClient(transport=ASGITransport(app=browser_lists.app), base_url="http://test") as client:
        response = await client.get("/knowledge")
        denied = await client.get("/knowledge/space/admin/list")
        scope = await client.get("/scope")
    assert [item["id"] for item in response.json()["data"]] == [22]
    browser_lists.runtime.list_visible_objects.assert_awaited_once()
    assert denied.json()["status_code"] == 19000
    assert scope.json() == {"pin": 101, "visible": [1, 101]}


async def test_child_admin_cannot_select_root_with_request_header(browser_lists):
    async with AsyncClient(transport=ASGITransport(app=browser_lists.app), base_url="http://test") as client:
        response = await client.get("/knowledge/space/admin/list", headers={"X-Management-Tenant": "1"})
    assert response.status_code == 409
    assert response.json()["status_code"] == 19704
