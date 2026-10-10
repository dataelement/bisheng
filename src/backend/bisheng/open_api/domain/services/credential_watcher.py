"""Revalidate credentials during an established Open API WebSocket session."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import WebSocket
from starlette.status import WS_1008_POLICY_VIOLATION

from bisheng.common.errcode.open_api import OpenApiAuthError, OpenApiEndpointUnregisteredError
from bisheng.open_api.domain.context import get_current_open_api_principal
from bisheng.open_api.domain.services.credential_validator import validate_bearer


@asynccontextmanager
async def watch_websocket_credential(
    websocket: WebSocket,
    *,
    interval_seconds: float = 3.0,
) -> AsyncIterator[None]:
    """Close a connected v2 socket when its credential becomes invalid."""

    expected = get_current_open_api_principal()

    async def monitor() -> None:
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                current = await validate_bearer(websocket.headers.get("Authorization"))
                if expected is None or current.credential_id != expected.credential_id:
                    raise OpenApiEndpointUnregisteredError()
            except OpenApiAuthError as exc:
                # The peer may already have closed while validation was running.
                with suppress(RuntimeError):
                    await websocket.close(code=WS_1008_POLICY_VIOLATION, reason=str(exc.code))
                return

    task = asyncio.create_task(monitor(), name="open-api-websocket-credential-watch")
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
