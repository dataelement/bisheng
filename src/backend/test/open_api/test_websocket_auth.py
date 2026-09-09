import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import WebSocketException
from starlette.websockets import WebSocket

from bisheng.common.errcode.open_api import OpenApiCredentialInvalidError
from bisheng.open_api.api.dependencies import (
    WS_POLICY_VIOLATION,
    verify_open_api_access,
    watch_websocket_credential,
)
from bisheng.open_api.domain.context import (
    OpenApiPrincipal,
    reset_current_open_api_principal,
    set_current_open_api_principal,
)


def _principal(credential_id: int = 5) -> OpenApiPrincipal:
    return OpenApiPrincipal(
        credential_id=credential_id,
        actor_kind="service_account",
        actor_id=9,
        actor_name="automation",
        tenant_id=3,
        resource_owner_user_id=7,
        scopes=frozenset({"workflow:invoke"}),
        authorization_subject_type="service_account",
        authorization_subject_id=9,
        effective_user_id=None,
    )


def _websocket(headers: list[tuple[bytes, bytes]] | None = None, query: bytes = b"") -> WebSocket:
    async def receive():
        return {"type": "websocket.disconnect"}

    async def send(_message):
        return None

    return WebSocket(
        {
            "type": "websocket",
            "asgi": {"version": "3.0"},
            "scheme": "ws",
            "path": "/api/v2/workflow/chat/workflow-id",
            "raw_path": b"/api/v2/workflow/chat/workflow-id",
            "query_string": query,
            "headers": headers or [],
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80),
            "subprotocols": [],
            "state": {},
        },
        receive,
        send,
    )


async def test_websocket_handshake_ignores_query_key_and_closes_with_1008() -> None:
    websocket = _websocket(query=b"api_key=bs-sak-not-a-header")
    dependency = verify_open_api_access(websocket)

    with pytest.raises(WebSocketException) as caught:
        await anext(dependency)

    assert caught.value.code == WS_POLICY_VIOLATION
    assert caught.value.reason == "26001"


async def test_connected_websocket_is_closed_when_credential_becomes_invalid(monkeypatch) -> None:
    websocket = SimpleNamespace(
        headers={"Authorization": "Bearer bs-sak-placeholder"},
        close=AsyncMock(),
    )
    monkeypatch.setattr(
        "bisheng.open_api.api.dependencies.validate_bearer",
        AsyncMock(side_effect=OpenApiCredentialInvalidError()),
    )
    token = set_current_open_api_principal(_principal())
    try:
        async with watch_websocket_credential(websocket, interval_seconds=0):
            for _ in range(20):
                if websocket.close.await_count:
                    break
                await asyncio.sleep(0)
    finally:
        reset_current_open_api_principal(token)

    websocket.close.assert_awaited_once_with(code=WS_POLICY_VIOLATION, reason="26002")


async def test_connected_websocket_rejects_a_different_credential(monkeypatch) -> None:
    websocket = SimpleNamespace(
        headers={"Authorization": "Bearer bs-sak-placeholder"},
        close=AsyncMock(),
    )
    monkeypatch.setattr(
        "bisheng.open_api.api.dependencies.validate_bearer",
        AsyncMock(return_value=_principal(credential_id=6)),
    )
    token = set_current_open_api_principal(_principal(credential_id=5))
    try:
        async with watch_websocket_credential(websocket, interval_seconds=0):
            for _ in range(20):
                if websocket.close.await_count:
                    break
                await asyncio.sleep(0)
    finally:
        reset_current_open_api_principal(token)

    websocket.close.assert_awaited_once_with(code=WS_POLICY_VIOLATION, reason="26031")
