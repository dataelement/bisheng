"""F113: request scope is authoritative, pinned and separate from account tenancy."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.open_api import (
    OpenApiAuthDependencyUnavailableError,
    ServiceAccountManagementScopeChangedError,
)
from bisheng.common.errcode.tenant import TenantDisabledError
from bisheng.core.context.tenant import get_current_tenant_id, get_visible_tenant_ids, set_admin_scope_tenant_id
from bisheng.open_api.domain.services import service_account_scope_service as service


def caller(*, super_admin=True, tenant=1):
    return SimpleNamespace(user_id=21, tenant_id=tenant, is_global_super=super_admin)


@pytest.fixture
def scope_ports(monkeypatch):
    monkeypatch.setattr(service.settings.multi_tenant, "enabled", True)
    current = AsyncMock(return_value=2)
    available = AsyncMock()
    monkeypatch.setattr(service, "current_admin_scope", current)
    monkeypatch.setattr(service, "ensure_service_account_tenant_available", available)
    return current, available


async def test_verified_scope_overrides_stale_middleware_and_restores_it(scope_ports):
    from bisheng.core.context.tenant import set_is_management_api

    management_token = set_is_management_api(True)
    old = set_admin_scope_tenant_id(9)
    try:
        async with service.ServiceAccountScopeService.bind_request(
            caller(), expected_tenant="2", writing=True
        ) as tenant:
            assert tenant == get_current_tenant_id() == 2
            assert get_visible_tenant_ids() == frozenset({2})
            assert service.ServiceAccountScopeService.admitted_tenant() == 2
            scope_ports[0].return_value = 3
            assert get_current_tenant_id() == 2
        assert get_current_tenant_id() == 9
        assert service.ServiceAccountScopeService.admitted_tenant() is None
    finally:
        old.var.reset(old)
        management_token.var.reset(management_token)


@pytest.mark.parametrize("selected,expected", [(None, "1"), (2, None), (2, "1"), (2, "0"), (2, "invalid")])
async def test_super_writes_require_selected_and_matching_form_scope(scope_ports, selected, expected):
    scope_ports[0].return_value = selected
    with pytest.raises(ServiceAccountManagementScopeChangedError):
        async with service.ServiceAccountScopeService.bind_request(caller(), expected_tenant=expected, writing=True):
            pytest.fail("Invalid management scope reached a write")


async def test_root_selection_is_explicit_one(scope_ports):
    scope_ports[0].return_value = 1
    async with service.ServiceAccountScopeService.bind_request(caller(), expected_tenant="1", writing=True):
        assert get_current_tenant_id() == 1


async def test_normal_admin_cannot_use_a_forged_scope_or_super_scope(scope_ports):
    async with service.ServiceAccountScopeService.bind_request(
        caller(super_admin=False, tenant=2), expected_tenant=None, writing=True
    ):
        assert get_current_tenant_id() == 2
    with pytest.raises(ServiceAccountManagementScopeChangedError):
        async with service.ServiceAccountScopeService.bind_request(
            caller(super_admin=False, tenant=2), expected_tenant="1", writing=True
        ):
            pytest.fail("A non-super administrator changed tenant")
    scope_ports[0].assert_not_awaited()


async def test_unavailable_tenant_and_scope_dependency_do_not_fall_back(scope_ports):
    scope_ports[1].side_effect = TenantDisabledError()
    with pytest.raises(TenantDisabledError):
        async with service.ServiceAccountScopeService.bind_request(caller(), expected_tenant="2", writing=True):
            pytest.fail("Disabled tenant reached a write")
    scope_ports[1].side_effect = None
    scope_ports[0].side_effect = OSError("F113 scope store unavailable")
    with pytest.raises(OpenApiAuthDependencyUnavailableError):
        async with service.ServiceAccountScopeService.bind_request(caller(), expected_tenant="2", writing=True):
            pytest.fail("Scope dependency fault reached a write")


async def test_single_tenant_retains_implicit_root_without_new_scope_dependency(scope_ports, monkeypatch):
    monkeypatch.setattr(service.settings.multi_tenant, "enabled", False)
    async with service.ServiceAccountScopeService.bind_request(caller(), expected_tenant=None, writing=True):
        assert get_current_tenant_id() == 1
    scope_ports[0].assert_not_awaited()
    scope_ports[1].assert_not_awaited()


async def test_new_read_with_stale_expected_scope_is_refused(scope_ports):
    with pytest.raises(ServiceAccountManagementScopeChangedError):
        async with service.ServiceAccountScopeService.bind_request(caller(), expected_tenant="1", writing=False):
            pytest.fail("Stale read reached the old tenant view")


def test_write_inventory_covers_every_account_mutation_and_keeps_filter_read_only():
    from bisheng.open_api.api.dependencies import get_service_account_manager, is_service_account_write
    from bisheng.open_api.api.endpoints.service_account import router as accounts
    from bisheng.open_api.api.endpoints.service_account_keys import router as keys

    count = 0
    for route in [*accounts.routes, *keys.routes]:
        assert any(dependency.call is get_service_account_manager for dependency in route.dependant.dependencies)
        for method in route.methods - {"GET", "HEAD", "OPTIONS"}:
            path = route.path.replace("{service_account_id}", "1").replace("{key_id}", "2")
            read_filter = path.endswith("/delegate-candidates:filter")
            assert is_service_account_write(method, "/api/v1" + path) is not read_filter
            count += not read_filter
    assert count == 10


async def test_scoped_owner_candidates_are_paginated_and_exclude_other_tenants(open_api_db):
    from bisheng.database.models.tenant import UserTenant
    from bisheng.open_api.domain.repositories.owner_repository import OwnerRepository
    from bisheng.user.domain.models.user import User

    async with open_api_db() as session:
        for uid, tid, deleted in [(21, 1, 0), (22, 2, 0), (23, 2, 0), (24, 2, 1)]:
            session.add(User(user_id=uid, user_name=f"F113-{uid}", password="", delete=deleted))
            session.add(UserTenant(user_id=uid, tenant_id=tid, is_active=1))
        await session.commit()
    first, total = await OwnerRepository.list_management_owners(2, keyword="F113", page=1, page_size=1)
    second, second_total = await OwnerRepository.list_management_owners(2, keyword="F113", page=2, page_size=1)
    assert total == second_total == 2
    assert [item.user_id for item in first + second] == [22, 23]
    assert all(item.tenant_id == 2 for item in first + second)


async def test_management_api_creation_follows_selected_tenant_and_rejects_old_form(
    open_api_db,
    fake_redis,
    audit_events,
    scope_ports,
    monkeypatch,
):
    import httpx
    from fastapi import FastAPI

    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.core.context.tenant import tenant_execution_scope
    from bisheng.database.models.tenant import UserTenant
    from bisheng.open_api.api.dependencies import get_service_account_admin
    from bisheng.open_api.api.endpoints.service_account import router as accounts
    from bisheng.open_api.api.endpoints.service_account_scope import router as scope_router
    from bisheng.open_api.api.exception_handlers import register_open_api_exception_handlers
    from bisheng.open_api.domain.models.service_account import ServiceAccount
    from bisheng.user.domain.models.user import User

    async with open_api_db() as session:
        for uid, tid in [(21, 1), (22, 2)]:
            session.add(User(user_id=uid, user_name=f"F113-owner-{uid}", password=""))
            session.add(UserTenant(user_id=uid, tenant_id=tid, is_active=1))
        await session.commit()
    admin = UserPayload(user_id=3, user_name="F113-admin", tenant_id=1, user_role=[], is_global_super=True)
    app = FastAPI()
    app.dependency_overrides[get_service_account_admin] = lambda: admin
    app.include_router(scope_router, prefix="/api/v1")
    app.include_router(accounts, prefix="/api/v1")
    register_open_api_exception_handlers(app)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        created = await client.post(
            "/api/v1/service-accounts",
            json={"name": "F113-child", "resource_owner_user_id": 22},
            headers={"X-Service-Account-Tenant": "2"},
        )
        assert created.status_code == 200 and created.json()["status_code"] == 200
        item = created.json()["data"]
        assert item["tenant_id"] == 2
        candidates = await client.get(
            "/api/v1/service-accounts/owner-candidates", headers={"X-Service-Account-Tenant": "2"}
        )
        assert [row["user_id"] for row in candidates.json()["data"]["data"]] == [22]
        scope_ports[0].return_value = 1
        refused = await client.patch(
            f"/api/v1/service-accounts/{item['id']}",
            json={"name": "must-not-save"},
            headers={"X-Service-Account-Tenant": "2"},
        )
        assert refused.json()["status_code"] == 26073
        no_header = await client.post(
            "/api/v1/service-accounts", json={"name": "no-scope", "resource_owner_user_id": 21}
        )
        assert no_header.json()["status_code"] == 26073
    with tenant_execution_scope(2):
        async with open_api_db() as session:
            stored = await session.get(ServiceAccount, item["id"])
            assert stored.name == "F113-child" and stored.tenant_id == 2


async def test_management_scope_http_requires_super_and_keeps_selection_when_target_unavailable(monkeypatch):
    """覆盖 AC: AC-17、AC-18、AC-19、AC-25; exercise the static scope endpoints."""
    import httpx
    from fastapi import FastAPI

    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.open_api.api.dependencies import get_service_account_admin
    from bisheng.open_api.api.endpoints.service_account_scope import router
    from bisheng.open_api.api.exception_handlers import register_open_api_exception_handlers

    monkeypatch.setattr(service.settings.multi_tenant, "enabled", True)
    current = {"scope_tenant_id": 2, "expires_at": None}

    async def read(_user_id):
        return dict(current)

    async def change(_user_id, tenant_id, _context):
        if tenant_id == 3:
            raise TenantDisabledError()
        current["scope_tenant_id"] = tenant_id
        return dict(current)

    monkeypatch.setattr(service, "read_service_account_scope", read)
    monkeypatch.setattr(service, "set_service_account_scope", change)
    monkeypatch.setattr(service, "ensure_service_account_tenant_available", AsyncMock())
    admin = UserPayload(user_id=3, user_name="F113-super", tenant_id=1, user_role=[], is_global_super=True)
    app = FastAPI()
    app.dependency_overrides[get_service_account_admin] = lambda: admin
    app.include_router(router, prefix="/api/v1")
    register_open_api_exception_handlers(app)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        url = "/api/v1/service-accounts/management-scope"
        response = await client.get(url)
        assert response.json()["data"]["scope_tenant_id"] == 2
        root = await client.put(url, json={"tenant_id": 1})
        assert root.json()["data"]["scope_tenant_id"] == 1
        refused = await client.put(url, json={"tenant_id": 3})
        assert refused.json()["status_code"] == TenantDisabledError.Code
        assert (await client.get(url)).json()["data"]["scope_tenant_id"] == 1
        for value in (None, 0, "2", -1):
            invalid = await client.put(url, json={"tenant_id": value})
            assert invalid.status_code == 422
        admin = admin.model_copy(update={"is_global_super": False, "tenant_id": 2})
        for response in (await client.get(url), await client.put(url, json={"tenant_id": 2})):
            assert response.json()["status_code"] == 26022
    assert current["scope_tenant_id"] == 1


@pytest.mark.parametrize("super_admin,writing", [(True, False), (True, True), (False, False)])
async def test_global_list_scope_is_retired_for_every_actor(scope_ports, super_admin, writing):
    from bisheng.core.context.tenant import is_tenant_filter_bypassed

    scope_ports[0].return_value = None
    with pytest.raises(ServiceAccountManagementScopeChangedError):
        async with service.ServiceAccountScopeService.bind_request(
            caller(super_admin=super_admin), expected_tenant="all", writing=writing
        ):
            pytest.fail("Retired global scope was admitted")
    assert not is_tenant_filter_bypassed()
    scope_ports[0].assert_not_awaited()
    scope_ports[1].assert_not_awaited()


async def test_list_http_is_concrete_and_rejects_legacy_global_requests(open_api_db, scope_ports):
    import httpx
    from fastapi import FastAPI

    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.database.models.tenant import Tenant
    from bisheng.open_api.api.dependencies import get_service_account_admin
    from bisheng.open_api.api.endpoints.service_account import router
    from bisheng.open_api.api.exception_handlers import register_open_api_exception_handlers
    from bisheng.open_api.domain.models.service_account import ServiceAccount

    with bypass_tenant_filter():
        async with open_api_db() as db:
            db.add_all([
                Tenant(id=1, tenant_code="root", tenant_name="Root organization"),
                Tenant(id=2, tenant_code="department", tenant_name="Department tenant"),
                ServiceAccount(id=1, tenant_id=1, name="root-account", resource_owner_user_id=21),
                ServiceAccount(id=2, tenant_id=2, name="department-account", resource_owner_user_id=22),
            ])
            await db.commit()
    operator = UserPayload(user_id=21, user_name="admin", tenant_id=1, user_role=[], is_global_super=True)
    app = FastAPI()
    app.dependency_overrides[get_service_account_admin] = lambda: operator
    app.include_router(router, prefix="/api/v1")
    register_open_api_exception_handlers(app)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        url = "/api/v1/service-accounts"
        blocked = await client.get(url, headers={"X-Service-Account-Tenant": "all"})
        assert blocked.json()["status_code"] == ServiceAccountManagementScopeChangedError.Code
        for selected in (1, 2):
            scope_ports[0].return_value = selected
            response = await client.get(url, headers={"X-Service-Account-Tenant": str(selected)})
            assert response.json()["status_code"] == 200
            assert response.json()["data"]["total"] == 1
            assert {row["tenant_id"] for row in response.json()["data"]["data"]} == {selected}
            assert response.json()["data"]["data"][0]["tenant_name"]
        operator.is_global_super = False
        operator.tenant_id = 2
        denied = await client.get(url, headers={"X-Service-Account-Tenant": "1"})
        assert denied.json()["status_code"] == ServiceAccountManagementScopeChangedError.Code
        own = await client.get(url, headers={"X-Service-Account-Tenant": "2"})
        assert own.json()["data"]["total"] == 1
        assert own.json()["data"]["data"][0]["tenant_id"] == 2
