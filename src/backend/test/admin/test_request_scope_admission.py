"""AC-50/52: admission is before parsing and spans ASGI stream lifetime."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from httpx import ASGITransport, AsyncClient

from bisheng.admin.application import request_admission
from bisheng.common.request_scope import RequestScope, ScopedAPIRouter
from bisheng.core.context.tenant import get_current_tenant_id


@pytest.fixture
def admitted_app(monkeypatch):
    user = SimpleNamespace(user_id=191, tenant_id=1, is_global_super=True)
    monkeypatch.setattr(request_admission, "authenticate_browser", AsyncMock(return_value=user))
    target = AsyncMock(return_value=SimpleNamespace(tenant_id=60, source="selected"))
    monkeypatch.setattr(request_admission, "request_target", target)
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    router = ScopedAPIRouter()

    @router.post("/write")
    async def write(body: dict):
        return {"tenant": get_current_tenant_id()}

    @router.get("/stream")
    async def stream():
        async def chunks():
            yield str(get_current_tenant_id())
            yield ":" + str(get_current_tenant_id())

        return StreamingResponse(chunks())

    @router.get("/legacy-header")
    async def legacy_header():
        return JSONResponse({"tenant": get_current_tenant_id()}, headers={"X-Management-Tenant": "65"})

    from bisheng.common.request_scope import request_scope

    for route in router.routes:
        request_scope(RequestScope.TENANT)(route.endpoint)
    app.include_router(router)
    request_admission.install_request_admission(app)
    return app, user, target


async def test_wrong_target_rejects_before_body_parsing(admitted_app):
    app, _, _ = admitted_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        result = await client.post("/write", headers={"X-Management-Tenant": "65"}, content="invalid-json")
    assert result.status_code == 409
    assert result.json()["status_code"] == 19704


async def test_stream_target_remains_until_last_chunk_and_is_restored(admitted_app):
    app, _, _ = admitted_app
    before = get_current_tenant_id()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        result = await client.get("/stream", headers={"X-Management-Tenant": "60"})
    assert result.text == "60:60"
    assert result.headers["X-Management-Tenant"] == "60"
    assert get_current_tenant_id() == before


async def test_ordinary_user_cannot_supply_foreign_target(admitted_app):
    app, user, target = admitted_app
    user.is_global_super = False
    user.tenant_id = 60
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        denied = await client.post("/write", headers={"X-Management-Tenant": "65"}, json={})
        allowed = await client.post("/write", json={})
    assert denied.status_code == 409
    assert allowed.json()["tenant"] == 60
    target.assert_not_awaited()


async def test_missing_super_target_and_query_conflict_are_denied(admitted_app):
    app, _, _ = admitted_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        missing = await client.post("/write", json={})
        conflict = await client.get("/stream?tenant_id=65", headers={"X-Management-Tenant": "60"})
    assert missing.status_code == 400 and missing.json()["status_code"] == 19703
    assert conflict.status_code == 409


async def test_credential_target_never_reads_browser_selection(admitted_app):
    app, user, target = admitted_app
    user._dsh_web_session_tenant_id = 1
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        allowed = await client.post("/write", json={})
        wrong = await client.get("/stream?tenant_id=65")
    assert allowed.json()["tenant"] == 1
    assert wrong.status_code == 409
    target.assert_not_awaited()


def test_bad_websocket_auth_closes_without_entering_business(monkeypatch):
    from fastapi import WebSocket
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    from bisheng.common.exceptions.auth import JWTDecodeError
    from bisheng.common.request_scope import request_scope

    monkeypatch.setattr(
        request_admission,
        "authenticate_browser",
        AsyncMock(side_effect=JWTDecodeError(status_code=401, message="invalid")),
    )
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

    @app.websocket("/ws")
    @request_scope(RequestScope.TENANT)
    async def socket(websocket: WebSocket):
        pytest.fail("unauthenticated socket must not enter business")

    request_admission.install_request_admission(app)
    with TestClient(app) as client, pytest.raises(WebSocketDisconnect) as failure:
        with client.websocket_connect("/ws"):
            pass
    assert failure.value.code == 1008


def test_websocket_target_is_frozen_after_selection_changes(monkeypatch):
    from fastapi import WebSocket
    from fastapi.testclient import TestClient

    from bisheng.common.request_scope import request_scope

    user = SimpleNamespace(user_id=191, tenant_id=1, is_global_super=True)
    monkeypatch.setattr(request_admission, "authenticate_browser", AsyncMock(return_value=user))
    selected = SimpleNamespace(tenant_id=60, source="selected")
    monkeypatch.setattr(request_admission, "request_target", AsyncMock(return_value=selected))
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

    @app.websocket("/ws")
    @request_scope(RequestScope.TENANT)
    async def socket(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_json({"tenant": get_current_tenant_id()})
        await websocket.receive_text()
        await websocket.send_json({"tenant": get_current_tenant_id()})
        await websocket.close()

    request_admission.install_request_admission(app)
    with TestClient(app) as client, client.websocket_connect("/ws") as connection:
        assert connection.receive_json()["tenant"] == 60
        selected.tenant_id = 65
        connection.send_text("next")
        assert connection.receive_json()["tenant"] == 60


async def test_frozen_response_target_replaces_legacy_headers_exactly_once(admitted_app):
    app, _, _ = admitted_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        result = await client.get("/legacy-header", headers={"X-Management-Tenant": "60"})
    assert result.headers.get_list("X-Management-Tenant") == ["60"]


@pytest.mark.parametrize(
    "kind,source,is_super,pin,visible",
    [
        (RequestScope.TENANT, "own", False, 60, frozenset({60})),
        (RequestScope.PERSONAL, "own", False, None, frozenset({60})),
        (RequestScope.TENANT, "credential", False, None, frozenset({60})),
        (RequestScope.TENANT, "selected", True, 60, frozenset({60})),
    ],
)
def test_verified_tenant_binding_isolates_business_rows_and_restores_context_on_failure(
    kind, source, is_super, pin, visible
):
    from bisheng.core.context.tenant import (
        get_admin_scope_tenant_id,
        get_is_management_api,
        get_visible_tenant_ids,
        tenant_execution_scope,
    )

    admitted = request_admission.AdmittedRequest(7, 60, 60, kind, is_super, source)
    with tenant_execution_scope(202):
        with pytest.raises(RuntimeError, match="business failure"):
            with request_admission.bind_admitted_scope(admitted):
                assert get_current_tenant_id() == 60
                assert get_admin_scope_tenant_id() == pin
                assert get_is_management_api() is (pin is not None)
                assert get_visible_tenant_ids() == visible
                raise RuntimeError("business failure")
        assert get_current_tenant_id() == 202
        assert get_admin_scope_tenant_id() is None
        assert not get_is_management_api()
        assert get_visible_tenant_ids() == frozenset({202})
