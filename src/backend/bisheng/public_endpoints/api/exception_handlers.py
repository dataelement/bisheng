"""True HTTP status handling for public v3 policy failures."""

from __future__ import annotations

from fastapi import FastAPI, Request, WebSocket
from fastapi import status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.websockets import WebSocketState

from bisheng.common.errcode.public_endpoints import PublicAccessError


async def handle_public_access_error(_request: Request, exc: PublicAccessError) -> JSONResponse:
    """Render the business code in the envelope, the transport status on the wire.

    ``data={}`` is explicit: ``to_dict`` otherwise fills it with the stringified
    exception and kwargs, and an anonymous channel must not leak either.
    """

    return JSONResponse(
        status_code=exc.http_status,
        content=jsonable_encoder(exc.to_dict(data={})),
    )


async def deny_public_websocket(websocket: WebSocket, exc: PublicAccessError) -> None:
    """Report a WebSocket denial in a form the browser can actually read.

    Closing before the handshake completes makes the server answer the upgrade
    with an HTTP error instead of a close frame; browsers surface that as a bare
    1006 with an empty reason, so the reason never arrives. Accepting first
    costs one frame and lets the existing client error handler resolve the
    business code. The close reason carries only the numeric code — it is capped
    at 123 bytes and is not reliably exposed by browser APIs.
    """

    if websocket.application_state == WebSocketState.CONNECTING:
        await websocket.accept()
    try:
        await websocket.send_json(
            {"category": "error", "type": "end", "message": exc.to_dict(data={})}
        )
    except Exception:  # peer already gone; the close below is still worth trying
        logger.opt(exception=True).debug("public websocket denial frame not delivered")
    await websocket.close(code=http_status.WS_1008_POLICY_VIOLATION, reason=str(exc.code))


def register_public_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(PublicAccessError, handle_public_access_error)


__all__ = [
    "deny_public_websocket",
    "handle_public_access_error",
    "register_public_exception_handlers",
]
