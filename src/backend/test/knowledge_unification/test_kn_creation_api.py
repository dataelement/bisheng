"""Actual unified HTTP routes call the real SQL-backed knowledge use cases."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient
from starlette.responses import JSONResponse

from bisheng.admin.application.tenant_scope import EffectiveManagementScope
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.core.context.tenant import management_tenant_scope
from bisheng.knowledge.api.dependencies import get_knowledge_space_service
from bisheng.knowledge.api.endpoints import knowledge_space as api
from bisheng.knowledge.domain.schemas.knowledge_space_schema import KnowledgeSpaceCreateReq
from bisheng.knowledge.domain.services import knowledge_creation_policy as policy
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from test.knowledge_unification import test_kn_list as list_fixtures
from test.knowledge_unification import test_kn_space_reference_lifecycle as creation_fixtures
from test.knowledge_unification import test_settings_repo as settings_fixtures

store = creation_fixtures.store
tenant = creation_fixtures.tenant
business = creation_fixtures.business
consumer = creation_fixtures.consumer
concrete_tenant = list_fixtures.concrete_tenant
catalog = list_fixtures.catalog
system_defaults = settings_fixtures.system_defaults


def app_for(service, user):
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")
    app.dependency_overrides[get_knowledge_space_service] = lambda: service
    app.dependency_overrides[UserPayload.get_login_user] = lambda: user

    # Keep the application error envelope without starting middleware/lifespan.
    @app.exception_handler(BaseErrorCode)
    async def business_error(request, error):
        return JSONResponse(error.return_resp_instance().model_dump(mode="json"))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return JSONResponse({"status_code": 422, "status_message": "invalid request"})

    return app


@pytest.fixture
def web_create(consumer, monkeypatch):
    context, service, _ = consumer
    context.user._runtime_credential_reference = {"kind": "web_session", "user_id": 7, "tenant_id": 101}
    monkeypatch.setattr(policy, "resolve_web_creation_identity", AsyncMock(return_value=context.user))
    monkeypatch.setattr(policy, "is_tenant_admin", AsyncMock(return_value=False))
    menu = AsyncMock()
    monkeypatch.setattr(UserPayload, "assert_effective_web_menu_contains", menu)
    scope = AsyncMock(return_value=EffectiveManagementScope(101, "own", None))
    monkeypatch.setattr(api, "resolve_management_scope", scope, raising=False)
    return SimpleNamespace(context=context, service=service, menu=menu, scope=scope, app=app_for(service, context.user))


async def post_create(web, payload, headers=None):
    async with AsyncClient(transport=ASGITransport(app=web.app), base_url="http://test") as client:
        with management_tenant_scope(101):
            return (await client.post("/api/v1/knowledge/space", json=payload, headers=headers)).json()


def test_creation_schema_exposes_only_frozen_optional_advanced_fields(system_defaults):
    request = KnowledgeSpaceCreateReq.model_validate(
        {
            "name": "typed",
            "embedding_model_id": 12,
            "processing_defaults": system_defaults.model_dump(mode="json"),
        }
    )
    assert request.embedding_model_id == 12
    assert request.processing_defaults == system_defaults


async def test_ordinary_creation_keeps_original_body_response_and_no_management_header_requirement(web_create):
    result = await post_create(web_create, {"name": "ordinary", "auth_type": "approval", "is_released": False})
    assert result["status_code"] == 200 and result["data"]["auth_type"] == "approval"
    row = next(
        item for item in creation_fixtures.state(web_create.context)["knowledge"] if item["id"] == result["data"]["id"]
    )
    assert row["model"] == "11" and row["processing_defaults"] is None
    web_create.scope.assert_not_awaited()
    web_create.menu.assert_not_awaited()


async def test_non_admin_with_real_creation_menu_can_create_with_explicit_model_and_defaults(
    web_create, system_defaults
):
    result = await post_create(
        web_create,
        {
            "name": "advanced",
            "embedding_model_id": 12,
            "processing_defaults": system_defaults.model_dump(mode="json"),
            "tenant_id": 202,
            "admin": True,
        },
        {"X-Management-Tenant": "101"},
    )
    assert result["status_code"] == 200
    row = next(
        item for item in creation_fixtures.state(web_create.context)["knowledge"] if item["id"] == result["data"]["id"]
    )
    assert row["tenant_id"] == 101 and row["model"] == "12"
    assert row["processing_defaults"] == system_defaults.model_dump(mode="json")
    assert row["processing_config_version"] == 0
    assert web_create.menu.await_count >= 2


@pytest.mark.parametrize("header,code", [(None, 19703), ("202", 19704), ("all", 19704)])
async def test_advanced_create_conditionally_rejects_missing_or_changed_scope_before_writes(web_create, header, code):
    before = creation_fixtures.state(web_create.context)
    result = await post_create(
        web_create,
        {"name": "advanced", "embedding_model_id": 12},
        {"X-Management-Tenant": header} if header is not None else None,
    )
    assert result["status_code"] == code
    assert creation_fixtures.state(web_create.context) == before


async def test_menu_denial_is_not_bypassed_by_advanced_fields_or_admin_body_flag(web_create):
    web_create.menu.side_effect = PermissionDeniedError()
    before = creation_fixtures.state(web_create.context)
    result = await post_create(
        web_create, {"name": "forged", "embedding_model_id": 12, "admin": True}, {"X-Management-Tenant": "101"}
    )
    assert result["status_code"] == PermissionDeniedError.Code
    assert creation_fixtures.state(web_create.context) == before


@pytest.mark.parametrize("model", [0, -1, True, "12"])
async def test_advanced_model_validation_rejects_invalid_wire_identity_without_creation(web_create, model):
    before = creation_fixtures.state(web_create.context)
    result = await post_create(web_create, {"name": "bad", "embedding_model_id": model}, {"X-Management-Tenant": "101"})
    assert result["status_code"] == 422
    assert creation_fixtures.state(web_create.context) == before


async def test_bad_defaults_do_not_create_a_partially_configured_space(web_create, system_defaults):
    defaults = system_defaults.model_dump(mode="json")
    defaults["document"]["chunk_overlap"] = defaults["document"]["chunk_size"] + 1
    before = creation_fixtures.state(web_create.context)
    result = await post_create(
        web_create, {"name": "bad defaults", "processing_defaults": defaults}, {"X-Management-Tenant": "101"}
    )
    assert result["status_code"] == 422 and creation_fixtures.state(web_create.context) == before


async def test_actual_list_routes_keep_cursor_and_admin_total_distinct(catalog):
    await catalog.seed([list_fixtures.row(ident) for ident in range(1, 4)] + [list_fixtures.row(4, tenant=202)])
    catalog.facts.allowed.add(1)
    app = app_for(catalog.service, catalog.service.login_user)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with management_tenant_scope(101):
            ordinary = (await client.get("/api/v1/knowledge/space/list?page_size=2")).json()
            catalog.service._permission_actor.return_value = PermissionActor(
                user_id=7, current_tenant_id=101, super_admin=True
            )
            admin = (await client.get("/api/v1/knowledge/space/admin/list?page=1&page_size=2")).json()
    assert ordinary["status_code"] == 200 and [item["id"] for item in ordinary["data"]["data"]] == [1]
    assert "total" not in ordinary["data"] and "has_more" in ordinary["data"]
    assert admin["status_code"] == 200 and admin["data"]["total"] == 3
    assert [item["id"] for item in admin["data"]["data"]] == [3, 2]
    assert "next_cursor" not in admin["data"]


async def test_direct_admin_route_does_not_accept_an_ordinary_owner(catalog):
    app = app_for(catalog.service, catalog.service.login_user)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with management_tenant_scope(101):
            result = (await client.get("/api/v1/knowledge/space/admin/list?tenant_id=202")).json()
    assert result["status_code"] == PermissionDeniedError.Code


@pytest.mark.parametrize("path", ["list?page_size=201", "admin/list?page=0"])
async def test_list_http_query_bounds_are_validated(catalog, path):
    app = app_for(catalog.service, catalog.service.login_user)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with management_tenant_scope(101):
            result = (await client.get("/api/v1/knowledge/space/" + path)).json()
    assert result["status_code"] == 422
