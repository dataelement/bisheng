"""HMAC-SHA256 request signature verification — F014 Gateway trust boundary.

The Gateway is the only trusted upstream allowed to call the F014 SSO sync
endpoints (``/internal/sso/login-sync``, ``/internal/sso/gateway-wecom-org-sync``,
``/departments/sync``). These
routes skip the ordinary JWT middleware and instead authenticate the caller
with a shared secret + detached signature in the ``X-Signature`` header.

**Signing string**::

    METHOD + "\n" + PATH + "\n" + raw_body

- ``METHOD`` — upper-case HTTP verb.
- ``PATH`` — request path (no query string; the two F014 endpoints don't
  use query strings).
- ``raw_body`` — bytes read from the request body before any parsing.

**Why a FastAPI Dependency, not an ASGI middleware?**

Starlette consumes the request body stream exactly once. If a middleware
reads the body to compute the signature, the downstream Pydantic parser
hangs waiting for bytes that will never arrive. The dependency pattern is
the officially supported workaround: read the body, stash the bytes on
``request._receive`` so the downstream parser reads the cached copy. This
keeps the concern scoped to the two F014 routes, avoids a global path
allow-list, and keeps body replay explicit.

**Fail-closed on empty secret.** If ``settings.sso_sync.gateway_hmac_secret``
is empty (unconfigured), the dependency rejects every request with 19301.
Silent acceptance would let unsigned requests through during mis-configured
rollouts — the whole point of HMAC would be defeated.
"""

import hashlib
import hmac

from fastapi import Request
from loguru import logger

from bisheng.common.errcode.sso_sync import SsoHmacInvalidError
from bisheng.common.services.config_service import settings


def compute_signature(
    method: str, path: str, raw_body: bytes, secret: str,
) -> str:
    """Compute the canonical HMAC-SHA256 hex digest for F014 Gateway calls.

    Exposed separately so tests + Gateway-side tooling can share the exact
    same signing function.
    """
    msg = f'{method.upper()}\n{path}\n'.encode() + (raw_body or b'')
    return hmac.new(
        secret.encode('utf-8'), msg, hashlib.sha256,
    ).hexdigest()


async def verify_hmac(request: Request) -> None:
    """FastAPI dependency that enforces HMAC-SHA256 on F014 endpoints.

    On success, leaves ``request._receive`` primed with the cached body so
    the downstream Pydantic parser can read it again. On any failure,
    raises :class:`SsoHmacInvalidError` which materialises as an HTTP error
    carrying the canonical 19301 code.
    """
    secret = settings.sso_sync.gateway_hmac_secret
    if not secret:
        logger.error(
            'F014 HMAC verification failed: sso_sync.gateway_hmac_secret '
            'is not configured; rejecting request (fail-closed).'
        )
        raise SsoHmacInvalidError.http_exception('hmac secret not configured')

    header_name = settings.sso_sync.signature_header or 'X-Signature'
    provided = (request.headers.get(header_name, '') or '').lower().strip()
    if not provided:
        logger.warning(
            'F014 HMAC verification failed: missing %s header from %s on %s',
            header_name,
            getattr(request.client, 'host', '?'),
            request.url.path,
        )
        raise SsoHmacInvalidError.http_exception('missing signature header')

    raw = await request.body()

    # Body replay: put the already-consumed bytes back on the receive
    # channel so the downstream Pydantic parser can read them. Using a
    # fresh closure per request keeps the coroutine idempotent even if
    # FastAPI reads the body more than once.
    async def _receive_replay():
        return {
            'type': 'http.request',
            'body': raw,
            'more_body': False,
        }

    request._receive = _receive_replay

    expected = compute_signature(
        request.method, request.url.path, raw, secret,
    )
    if not hmac.compare_digest(expected, provided):
        logger.warning(
            'F014 HMAC verification failed: signature mismatch from %s on %s',
            getattr(request.client, 'host', '?'),
            request.url.path,
        )
        raise SsoHmacInvalidError.http_exception('invalid signature')
