"""Credential rejection must precede expensive identity runtime assembly."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from bisheng.common.errcode.sso_sync import KunlianDependencyUnavailableError
from bisheng.open_api.application import kunlian_http
from bisheng.open_api.domain.services.kunlian_credential import KunlianAccessError


@pytest.mark.parametrize("authorization", [None, "Bearer invalid"])
async def test_invalid_key_never_builds_identity_runtime(monkeypatch, authorization):
    from bisheng.sso_sync.application import kunlian_identity

    factory = AsyncMock(side_effect=KunlianDependencyUnavailableError())
    monkeypatch.setattr(kunlian_identity, "get_kunlian_identity_application", factory)
    credentials = SimpleNamespace(authenticate_caller=AsyncMock(side_effect=KunlianAccessError("UNAUTHENTICATED")))
    monkeypatch.setattr(kunlian_http, "KunlianCredentialService", lambda: credentials)
    app = FastAPI()
    router = APIRouter(route_class=kunlian_http.KunlianApiRoute)

    @router.get("/probe")
    @kunlian_http.kunlian_capability("read")
    async def endpoint(access=Depends(kunlian_http.get_kunlian_request_user)):
        pytest.fail("invalid key cannot enter business")

    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.get(
            "/probe",
            params={"user_account": "account-a"},
            headers={"Authorization": authorization} if authorization else {},
        )
    assert response.status_code == 401
    factory.assert_not_awaited()
    credentials.authenticate_caller.assert_awaited_once_with(authorization, capability="read")


async def test_valid_key_resolves_lazy_identity_only_after_authentication():
    from bisheng.open_api.application.kunlian_access import KunlianAccessService

    events = []

    async def authenticate_caller(authorization, *, capability):
        events.append("key")
        assert (authorization, capability) == ("Bearer valid", "read")
        return SimpleNamespace(credential_id=3, integration_id="partner", connection_id="trusted")

    async def resolve_account(*, connection_id, user_account):
        events.append("account")
        assert (connection_id, user_account) == ("trusted", "account-a")
        return SimpleNamespace(user_id=17, tenant_id=7, external_tenant_id="tenant", external_user_id="subject")

    async def validate_reference(credential_id, *, integration_id, connection_id, external_tenant_id, capability):
        events.append("scope")
        assert (credential_id, integration_id, connection_id, external_tenant_id, capability) == (
            3,
            "partner",
            "trusted",
            "tenant",
            "read",
        )
        return SimpleNamespace(credential_id=3, integration_id="partner", connection_id="trusted")

    async def factory():
        events.append("factory")
        return SimpleNamespace(resolve=resolve)

    async def resolve(**kwargs):
        events.append("resolve")
        assert kwargs == {"connection_id": "trusted", "external_tenant_id": "tenant", "external_user_id": "subject"}
        return SimpleNamespace(user_id=17, tenant_id=7, is_global_super=False)

    service = KunlianAccessService(
        SimpleNamespace(authenticate_caller=authenticate_caller, validate_reference=validate_reference),
        factory,
        account_resolver=SimpleNamespace(resolve_account=resolve_account),
        privilege_reader=AsyncMock(return_value=(False, False)),
    )
    async with service.use_user("Bearer valid", "account-a", capability="read") as access:
        assert access.user.user_id == 17
    assert events == ["key", "account", "scope", "factory", "resolve"]
