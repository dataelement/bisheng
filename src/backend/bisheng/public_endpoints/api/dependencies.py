"""FastAPI dependencies for the anonymous public v3 surface."""

from __future__ import annotations

from fastapi import WebSocket, WebSocketException, status
from starlette.requests import HTTPConnection

from bisheng.common.errcode.public_endpoints import PublicAccessError
from bisheng.public_endpoints.domain.services.guest_policy import reject_identity_headers


async def verify_public_access(conn: HTTPConnection) -> None:
    """Apply channel-wide rules that do not require resolving a resource."""

    try:
        reject_identity_headers(conn.headers)
    except PublicAccessError as exc:
        if isinstance(conn, WebSocket):
            # Raised before the handshake completes, so the reason is not
            # readable by browsers (they see a bare 1006). That is acceptable
            # here: only a deliberately constructed request reaches this branch,
            # never a share-link visitor. The endpoints themselves accept first
            # (see ``deny_public_websocket``) because their denials are
            # visitor-facing.
            raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason=exc.message) from exc
        raise
    # v3 intentionally ignores JWT/API-key credentials. They grant no extra
    # access and are never parsed into a principal on this channel.


__all__ = ["verify_public_access"]
