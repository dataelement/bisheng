"""Desktop credentials retain online session checks and tenant-only market access."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import jwt
import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.dsh import DshSessionRevokedError
from bisheng.core.context import tenant as context
from bisheng.dsh.domain.services.access import DshAccessService
from bisheng.dsh_market.api.auth import MarketActor, market_actor, market_admin
from bisheng.utils.http_middleware import CustomMiddleware, owns_dsh_credential
from test.dsh.test_access import Identities, Keys, token


class Sessions:
    active = True

    async def validate(self, principal):
        assert principal.seat_id is None and principal.grant_version is None
        if not self.active:
            raise DshSessionRevokedError()


@pytest.fixture
def market_app(monkeypatch):
    import bisheng.dsh.access_runtime as runtime

    sessions = Sessions()
    access = DshAccessService("test-issuer", Keys(), Identities(), sessions)
    monkeypatch.setattr(runtime, "get_runtime", AsyncMock(return_value=SimpleNamespace(access=access)))
    app = FastAPI()
    app.add_middleware(CustomMiddleware)

    @app.exception_handler(BaseErrorCode)
    async def error_handler(request, error):
        return JSONResponse(error.to_dict())

    @app.get("/api/v1/dsh/market/catalog")
    async def catalog(request: Request, actor: MarketActor = Depends(market_actor)):
        if request.headers.get("x-test-admin"):
            await market_admin(request, actor)
        return {
            "tenant": actor.tenant_id,
            "user": actor.user_id,
            "desktop": actor.desktop,
            "visible": sorted(context.get_visible_tenant_ids()),
            "bypass": context.is_tenant_filter_bypassed(),
        }

    return app, sessions


async def test_verified_desktop_identity_selects_its_tenant(market_app):
    app, _ = market_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://example.test") as client:
        for tenant in (2, 3):
            result = await client.get(
                "/api/v1/dsh/market/catalog",
                headers={
                    "Authorization": "Bearer " + token(tenant_id=str(tenant)),
                    "x-dsh-market-tenant": "99",
                    "Cookie": "access_token_cookie=stale-browser-cookie",
                },
            )
            assert result.status_code == 200
            assert result.json() == {
                "tenant": tenant,
                "user": 1001,
                "desktop": True,
                "visible": [tenant],
                "bypass": False,
            }


async def test_revoked_session_and_invalid_token_signature_are_rejected(market_app):
    app, sessions = market_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://example.test") as client:
        sessions.active = False
        result = await client.get("/api/v1/dsh/market/catalog", headers={"Authorization": "Bearer " + token()})
        assert result.status_code == 401
        sessions.active = True
        claims = jwt.decode(token(), options={"verify_signature": False})
        forged = jwt.encode(
            claims,
            b"wrong-test-key-for-signature-check",
            algorithm="HS256",
            headers={"kid": "test-key", "typ": "bisheng-dsh-access+jwt"},
        )
        result = await client.get("/api/v1/dsh/market/catalog", headers={"Authorization": "Bearer " + forged})
        assert result.status_code == 401


async def test_desktop_credential_cannot_manage_market(market_app):
    app, _ = market_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://example.test") as client:
        result = await client.get(
            "/api/v1/dsh/market/catalog",
            headers={
                "Authorization": "Bearer " + token(),
                "x-test-admin": "1",
            },
        )
        assert result.json()["status_code"] == 26204


@pytest.mark.parametrize(
    "method,path,owned",
    [
        ("GET", "/api/v1/dsh/market/catalog", True),
        ("GET", "/api/v1/dsh/market/capabilities", True),
        ("POST", "/api/v1/dsh/market/sync", True),
        ("GET", "/api/v1/dsh/market/plugins/" + "a" * 32 + "/versions/" + "b" * 32 + "/artifact", True),
        ("GET", "/api/v1/dsh/market/admin/plugins", False),
        ("POST", "/api/v1/dsh/market/admin/imports", False),
        ("POST", "/api/v1/dsh/market/catalog", False),
        ("GET", "/api/v1/dsh/market/catalog/extra", False),
        ("GET", "/api/v1/dsh/market/plugins/bad/versions/bad/artifact", False),
    ],
)
def test_market_route_credential_ownership(method, path, owned):
    assert owns_dsh_credential(method, path) is owned


def test_market_error_code_survives_platform_exception_envelope():
    import json

    from fastapi import HTTPException
    from starlette.requests import Request

    from bisheng.main import handle_http_exception

    request = Request({"type": "http", "method": "GET", "path": "/api/v1/dsh/market/catalog", "headers": []})
    response = handle_http_exception(
        request, HTTPException(401, {"error": "Session revoked", "code": "session_revoked"})
    )
    assert response.status_code == 200
    assert json.loads(response.body) == {
        "status_code": 401,
        "status_message": "Session revoked",
        "data": {"code": "session_revoked"},
    }
