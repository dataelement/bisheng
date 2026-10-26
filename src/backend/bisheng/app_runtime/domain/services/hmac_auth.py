"""HMAC-SHA256 authentication for app-proxy → backend calls.

The signing string is byte-for-byte the one F014's gateway hook and
runtime-manager already use::

    METHOD + "\\n" + PATH + "\\n" + raw_body

Identical on purpose: three processes now speak it (backend↔manager,
app-proxy↔backend, app-proxy↔manager), and one scheme with one test is far
safer than three that are "almost" the same.

Two properties carry weight:

* **Empty secret fails closed.** A rollout that forgot ``proxy_hmac_secret``
  would otherwise accept unsigned calls to an endpoint that answers "who is
  this user and here is their identity material" — i.e. anything that can reach
  the port could mint injected identity for every hosted app.
* **A dependency, not middleware.** Starlette consumes the request body once; a
  middleware that read it to verify the signature would leave the downstream
  Pydantic parser waiting for bytes that never arrive. The dependency stashes
  the consumed bytes back on ``request._receive`` — the same work-around F014
  uses.
"""

from __future__ import annotations

import hashlib
import hmac

from fastapi import Request
from loguru import logger

from bisheng.common.services.config_service import settings

SIGNATURE_HEADER = "X-Signature"


class ProxyHmacRejectedError(Exception):
    """The caller's signature was missing, wrong, or unverifiable (no shared secret).

    Defined here rather than next to its HTTP handler so the domain layer does
    not import the API layer (C1). ``api/exception_handlers.py`` turns it into a
    real 401 — the one status app-proxy reads as "our shared secret is wrong"
    rather than "this visitor may not enter".
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def compute_signature(method: str, path: str, raw_body: bytes, secret: str) -> str:
    """Canonical HMAC-SHA256 hex digest, shared with app-proxy and runtime-manager."""
    msg = f"{method.upper()}\n{path}\n".encode() + (raw_body or b"")
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


async def verify_proxy_hmac(request: Request) -> None:
    """FastAPI dependency guarding the internal app-proxy endpoints."""
    secret = settings.app_runtime.proxy_hmac_secret
    if not secret:
        logger.error("app_runtime internal endpoint rejected: proxy_hmac_secret is not configured (fail-closed)")
        raise ProxyHmacRejectedError("app-proxy hmac secret not configured")

    provided = (request.headers.get(SIGNATURE_HEADER, "") or "").lower().strip()
    if not provided:
        raise ProxyHmacRejectedError("missing signature header")

    raw = await request.body()

    async def _receive_replay():
        return {"type": "http.request", "body": raw, "more_body": False}

    request._receive = _receive_replay

    expected = compute_signature(request.method, request.url.path, raw, secret)
    # Constant time: the header is attacker supplied, and a byte-wise ``==``
    # leaks the prefix length through timing.
    if not hmac.compare_digest(expected, provided):
        logger.warning("app_runtime internal endpoint rejected: signature mismatch on {}", request.url.path)
        raise ProxyHmacRejectedError("invalid signature")
