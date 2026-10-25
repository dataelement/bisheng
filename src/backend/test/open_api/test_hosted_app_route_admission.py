"""F055 AC-52 — which ``/api/v2`` routes a hosted application is admitted to.

The declaration buys scopes, and a scope is much coarser than the set of routes
an application should get from it: declaring one knowledge base derives
``knowledge:read``, which covers seven routes. Six of them build a *natural
person* out of the credential — ``get_open_api_operator()`` resolves to the
application's owner, with the owner's roles — or, in ``download_statistic``'s
case, hand out any ``/app/data`` log file to whoever holds the scope. Only the
seventh goes through the capability bus.

So admission is decided per route and defaults to refusal. This file is the
behavioural half; ``test_open_api_route_matrix`` holds the list of routes that
opted in, and ``test_capability_knowledge`` covers the second line of defence
inside ``get_open_api_operator`` itself (the MCP face and any other non-APIRoute
entrance never reaches the marker).
"""

from unittest.mock import AsyncMock

from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from bisheng.open_api.api.dependencies import verify_open_api_access
from bisheng.open_api.api.exception_handlers import register_open_api_exception_handlers
from bisheng.open_api.domain.scopes import open_api_scope
from test.open_api.model_gateway_fixtures import hosted_app_principal, service_account_principal


def _app() -> FastAPI:
    """Two routes under the real dependency: one opted in, one not."""

    app = FastAPI()
    register_open_api_exception_handlers(app)
    router = APIRouter(prefix="/api/v2", dependencies=[Depends(verify_open_api_access)])

    inner = APIRouter(prefix="/filelib")

    @inner.post("/retrieve")
    @open_api_scope("knowledge:read", hosted_app=True)
    async def _retrieve() -> dict:
        return {"ok": "bus"}

    @inner.get("/")
    @open_api_scope("knowledge:read")
    async def _list() -> dict:
        return {"ok": "owner"}

    router.include_router(inner)
    app.include_router(router)
    return app


def _admit(monkeypatch, principal) -> None:
    monkeypatch.setattr(
        "bisheng.open_api.api.dependencies.validate_bearer",
        AsyncMock(return_value=principal),
    )


async def _call(method: str, path: str):
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        return await client.request(method, path, headers={"Authorization": "Bearer k"})


async def test_a_hosted_application_reaches_the_capability_face(monkeypatch):
    _admit(monkeypatch, hosted_app_principal(scopes=frozenset({"knowledge:read"})))

    response = await _call("POST", "/api/v2/filelib/retrieve")

    assert response.status_code == 200


async def test_the_same_scope_does_not_open_the_owner_executing_neighbours(monkeypatch):
    """The whole point: same credential, same scope, different route."""
    _admit(monkeypatch, hosted_app_principal(scopes=frozenset({"knowledge:read"})))

    response = await _call("GET", "/api/v2/filelib/")

    assert response.status_code == 403
    assert response.json()["status_code"] == 26052


async def test_a_service_account_is_unaffected(monkeypatch):
    """The refusal is keyed on the subject kind, not on the route."""
    _admit(monkeypatch, service_account_principal(scopes=frozenset({"knowledge:read"})))

    response = await _call("GET", "/api/v2/filelib/")

    assert response.status_code == 200
