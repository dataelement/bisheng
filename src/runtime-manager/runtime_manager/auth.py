"""HMAC-SHA256 request authentication for every runtime-manager RPC.

Signing string is byte-for-byte the one the platform already uses for the F014
Gateway trust boundary (``bisheng/sso_sync/domain/services/hmac_auth.py``)::

    METHOD + "\\n" + PATH + "\\n" + raw_body

Deliberately identical so that the backend client, the app-proxy client and
this server can be reasoned about as one scheme instead of three. Three
properties are load bearing and each is covered by a test:

* **PATH excludes the query string.** ``GET /v1/apps/{id}/logs?tail=200`` signs
  only the path. Query parameters on the read side are filters, not authority —
  and keeping them out of the signature is what lets the backend build a URL
  with ``httpx.params`` without re-deriving the signature.
* **``hmac.compare_digest``**, never ``==`` — the header is attacker supplied.
* **Empty secret fails closed.** A mis-configured rollout that silently accepts
  unsigned requests would hand the docker socket to anything that can reach
  127.0.0.1:8091, which is the exact opposite of why this process exists.

Why a FastAPI dependency and not ASGI middleware: Starlette consumes the
request body stream exactly once, so a middleware that reads the body to verify
the signature makes the downstream Pydantic parser hang. The dependency stashes
the consumed bytes back on ``request._receive`` — the officially supported
work-around, and the same one F014 uses.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

from fastapi import Request

from runtime_manager.config import get_config
from runtime_manager.errors import UnauthorizedError

logger = logging.getLogger(__name__)


def compute_signature(method: str, path: str, raw_body: bytes, secret: str) -> str:
    """Canonical HMAC-SHA256 hex digest. Shared by server, tests and clients."""
    msg = f"{method.upper()}\n{path}\n".encode() + (raw_body or b"")
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


async def verify_hmac(request: Request) -> None:
    """FastAPI dependency enforcing HMAC on every ``/v1/**`` route."""
    config = get_config()
    secret = config.hmac_secret
    if not secret:
        logger.error(
            "runtime-manager HMAC verification failed: RTM_HMAC_SECRET is not "
            "configured; rejecting request (fail-closed)."
        )
        raise UnauthorizedError("hmac secret not configured")

    provided = (request.headers.get(config.signature_header, "") or "").lower().strip()
    if not provided:
        logger.warning(
            "runtime-manager HMAC verification failed: missing %s header on %s",
            config.signature_header,
            request.url.path,
        )
        raise UnauthorizedError("missing signature header")

    raw = await request.body()

    async def _receive_replay():
        return {"type": "http.request", "body": raw, "more_body": False}

    request._receive = _receive_replay

    expected = compute_signature(request.method, request.url.path, raw, secret)
    if not hmac.compare_digest(expected, provided):
        logger.warning(
            "runtime-manager HMAC verification failed: signature mismatch on %s",
            request.url.path,
        )
        raise UnauthorizedError("invalid signature")
