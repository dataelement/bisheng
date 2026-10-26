"""F052 T206a — the MCP address the access-information panel copies.

One address, derived the same way the skill packs derive theirs, so the panel
never composes a second URL of its own. It carries no credential: the key is
issued separately and travels in the Authorization header.
"""

from __future__ import annotations

import json

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from bisheng.common.services.config_service import settings
from bisheng.dev_toolkit.api.endpoints.distribution import router


def build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return app


async def versions(headers: dict[str, str] | None = None) -> dict:
    async with AsyncClient(transport=ASGITransport(app=build_app()), base_url="http://internal") as client:
        response = await client.get("/api/v1/dev-toolkit/versions", headers=headers or {})
    assert response.status_code == 200
    return response.json()["data"]


async def test_versions_carries_the_mcp_url_from_the_configured_public_base_url(monkeypatch):
    monkeypatch.setattr(settings.open_api, "public_base_url", "https://kb.example.com")
    payload = await versions()
    assert payload["mcp"] == {
        "url": "https://kb.example.com/api/v2/mcp",
        "transport": "streamable-http",
        "auth": "bearer",
    }


async def test_versions_mcp_url_falls_back_to_the_forwarded_headers(monkeypatch):
    """Behind nginx the backend sees the internal upstream, not what the user typed."""

    monkeypatch.setattr(settings.open_api, "public_base_url", "")
    payload = await versions({"X-Forwarded-Proto": "https", "X-Forwarded-Host": "bisheng.corp.example.com"})
    assert payload["mcp"]["url"] == "https://bisheng.corp.example.com/api/v2/mcp"


async def test_versions_carries_the_model_face_base_url(monkeypatch):
    """F053 T046: the slot F052 held open is filled from F051's one producer.

    ``model_gateway_base_url`` is what ``GET /api/v2/auth/whoami`` answers with
    too (F051 AC-30), so the access-information panel copies the same spelling a
    hosted app is injected with — nobody appends ``/api/v2/model/v1`` twice.
    """

    monkeypatch.setattr(settings.open_api, "public_base_url", "https://kb.example.com")
    payload = await versions()
    assert payload["model"] == {
        "base_url": "https://kb.example.com/api/v2/model/v1",
        "protocol": "openai",
        "auth": "bearer",
    }


async def test_the_model_and_mcp_addresses_share_one_origin(monkeypatch):
    """Two addresses, one derivation — a second origin would be a second bug."""

    monkeypatch.setattr(settings.open_api, "public_base_url", "")
    payload = await versions({"X-Forwarded-Proto": "https", "X-Forwarded-Host": "bisheng.corp.example.com"})
    assert payload["model"]["base_url"] == "https://bisheng.corp.example.com/api/v2/model/v1"
    assert payload["mcp"]["url"].startswith("https://bisheng.corp.example.com/")


async def test_versions_carries_the_platform_base_url_every_other_address_is_built_on(monkeypatch):
    """AC-44's 平台地址 and installer link must not come from a second source.

    The panel shows five addresses side by side and an administrator forwards
    all five at once. Two of them (`bisheng login <地址>` and the installer link)
    would otherwise be built from the browser's origin, which on a path-prefix
    deployment is missing the prefix the other three carry — a login command
    that 404s printed directly under an MCP address that works.
    """

    monkeypatch.setattr(settings.open_api, "public_base_url", "https://portal.example.com/bisheng")
    payload = await versions()
    base = payload["platform"]["base_url"]
    assert base == "https://portal.example.com/bisheng"
    # Same prefix as the two addresses the panel does not build itself.
    assert payload["mcp"]["url"] == f"{base}/api/v2/mcp"
    assert payload["model"]["base_url"] == f"{base}/api/v2/model/v1"


async def test_the_platform_base_url_follows_the_browsers_own_request_when_unconfigured(monkeypatch):
    """No operator declaration: it is the address *this* request arrived at.

    So a plain deployment sees exactly what `window.location.origin` would have
    given, and nothing regresses by preferring this field over the origin.
    """

    monkeypatch.setattr(settings.open_api, "public_base_url", "")
    payload = await versions({"X-Forwarded-Proto": "https", "X-Forwarded-Host": "bisheng.corp.example.com"})
    assert payload["platform"]["base_url"] == "https://bisheng.corp.example.com"


async def test_the_versions_payload_carries_no_credential_material():
    payload = json.dumps(await versions())
    for marker in ("bs-sak-", "bs-pat-", "Authorization", "token"):
        assert marker not in payload


def test_the_address_is_absent_where_the_open_capability_layer_is_not_deployed():
    """Not a branch in the handler — the whole router is only mounted with the layer on.

    Asserting the *mechanism* rather than a response: a future refactor that
    made the include unconditional would leave the address advertised on a
    deployment that answers 404 for it.
    """

    import inspect

    from bisheng.api import router as router_module

    source = inspect.getsource(router_module)
    assert "if settings.open_platform.enabled:" in source
    assert "router.include_router(dev_toolkit_router)" in source
