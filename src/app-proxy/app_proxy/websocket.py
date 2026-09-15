"""WebSocket reverse proxying and the three invariants of design D6.

The upgrade takes the **same** road as an HTTP request up to the forward: the
verdict is the backend's (``main.handle_entry_ws`` asked it before calling in
here), the header list is built by the one function the HTTP path uses
(:func:`app_proxy.proxy.upstream_headers_for` — strip the whole ``x-bisheng-``
equivalence class, inject the ten, rewrite ``X-Forwarded-*``, AC-32), the
address is the manager's with the same invalidate-and-retry-once (D5.1). What
is specific to sockets is what happens *after* the handshake, and that is the
three invariants:

① **The authorisation is fixed at the handshake.** A socket is asked once, so
  the answer is given an expiry: ``min(OBO remaining, ws_max_lifetime) +
  jitter``, after which the proxy closes it with ``4001``. The frontend
  reconnects and gets a fresh verdict — that is the mechanism by which a
  long-lived connection follows permission changes at all.
② **A revoke / stop / delete reaches open sockets actively.** The backend posts
  to ``/internal/connections/close`` and the registry
  (:mod:`app_proxy.connections`) ends the matching sockets. Because that push
  is per-process and best-effort, every connection also re-asks the verdict
  every ``ws_reauthorize_interval_seconds`` and closes itself on a non-allow —
  the bound a customer can rely on whatever the topology.
③ **Re-handshake is normal.** Every close code the proxy emits means
  "reconnect" (see ``login_handoff.WS_CLOSE_CODES``); the hosted-app tutorial
  and the deploy-hosting skill tell app authors to treat it that way.

The pumps are two tasks, not a select loop, and the deadline / revocation /
re-authorisation are three more. Whichever finishes first decides the close
code; the rest are cancelled. Both sides are always told the same code, so the
app and the browser have one story about why the connection ended.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import anyio
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from app_proxy import connections
from app_proxy.authz import Verdict, authorize
from app_proxy.config import get_config
from app_proxy.login_handoff import WS_CLOSE_EXPIRED, ws_close_code
from app_proxy.pages import PAGE_DEPLOYING, PAGE_RECOVERING
from app_proxy.proxy import log_forged_headers, upstream_headers_for
from app_proxy.routing import resolve_upstream, strip_entry_prefix

logger = logging.getLogger(__name__)


class UpstreamSocket(Protocol):
    """The slice of ``websockets.asyncio.client.ClientConnection`` we depend on."""

    subprotocol: str | None
    close_code: int | None
    close_reason: str | None

    async def recv(self) -> str | bytes: ...
    async def send(self, message: str | bytes) -> None: ...
    async def close(self, code: int = 1000, reason: str = "") -> None: ...


#: ``(url, headers, subprotocols, connect_timeout) -> socket``. Injectable so
#: the suite can route ``ws://172.20.x.y`` to a loopback server the same way
#: ``UpstreamTransport`` does for HTTP.
Connector = Callable[[str, list[tuple[str, str]], list[str], float], Awaitable[UpstreamSocket]]

#: Handshake headers the browser sent for *its* connection. They must not be
#: replayed onto ours — the client library generates its own key / version /
#: extensions, and a duplicated ``Sec-WebSocket-Key`` fails the upgrade at the
#: app. ``Sec-WebSocket-Protocol`` travels as the ``subprotocols`` argument.
_HANDSHAKE_HEADERS = frozenset(
    {
        "sec-websocket-key",
        "sec-websocket-version",
        "sec-websocket-extensions",
        "sec-websocket-protocol",
        "sec-websocket-accept",
    }
)

#: Codes a close frame may legitimately carry (RFC 6455 §7.4). Anything else
#: we observed (1005 "no status", 1006 "abnormal", 1015 "TLS") is a local
#: observation, not something either peer sent, and cannot be forwarded as-is.
_SENDABLE_CODES = frozenset({1000, 1001, 1002, 1003, 1007, 1008, 1009, 1010, 1011})

_connector: Connector | None = None


def set_upstream_connector(connector: Connector | None) -> None:
    """Test / bootstrap seam."""
    global _connector
    _connector = connector


async def _default_connector(
    url: str, headers: list[tuple[str, str]], subprotocols: list[str], timeout: float
) -> UpstreamSocket:
    from websockets.asyncio.client import connect

    return await connect(
        url,
        additional_headers=headers,
        subprotocols=subprotocols or None,  # type: ignore[arg-type]
        open_timeout=timeout,
        # Never the process's HTTP(S)_PROXY: the upstream is a bridge address
        # on this host, and an environment proxy would send it off-box.
        proxy=None,
        # Hosted apps may push large frames; the browser side is bounded by
        # uvicorn's own limit already.
        max_size=None,
        # Keepalive pings are ours to send: a browser cannot ping, and an app
        # that stops answering pongs is an app the visitor should reconnect to.
        ping_interval=20,
        ping_timeout=20,
    )


def get_upstream_connector() -> Connector:
    return _connector or _default_connector


# ---------------------------------------------------------------------------
# invariant ① — lifetime
# ---------------------------------------------------------------------------


def obo_expiry(payload_or_verdict: Any, *, obo_token: str | None) -> float | None:
    """When the visitor's on-behalf-of token stops being valid, as epoch seconds.

    The backend states it outright (``obo_expires_at``) since T080; an older
    backend only sends the token, whose ``exp`` claim is readable without the
    key — and *only* read, never trusted for anything but shortening a
    lifetime. Without a token at all (``obo_secret`` unconfigured) the cap is
    the only bound.
    """
    explicit = getattr(payload_or_verdict, "obo_expires_at", None)
    if explicit is None and isinstance(payload_or_verdict, dict):
        explicit = payload_or_verdict.get("obo_expires_at")
    if isinstance(explicit, int | float) and not isinstance(explicit, bool):
        return float(explicit)
    if not obo_token:
        return None
    try:
        segment = obo_token.split(".")[1]
        padded = segment + "=" * (-len(segment) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
        exp = claims.get("exp")
        return float(exp) if isinstance(exp, int | float) else None
    except (IndexError, ValueError, TypeError, AttributeError):
        return None


def connection_lifetime(*, obo_expires_at: float | None, now: float, max_lifetime: float, jitter: float) -> float:
    """``min(OBO remaining, cap) + uniform(0, jitter)``, never negative (D6 ①).

    The jitter is added, not subtracted: a burst of tabs opened together must
    not all expire together, and shaving the OBO bound would buy nothing —
    the app receives the token once, at the handshake, and reads it then.
    """
    bound = float(max_lifetime)
    if obo_expires_at is not None:
        bound = min(bound, obo_expires_at - now)
    bound = max(0.0, bound)
    return bound + (random.uniform(0, jitter) if jitter > 0 else 0.0)


# ---------------------------------------------------------------------------
# the proxied connection
# ---------------------------------------------------------------------------


def _sendable(code: int | None, *, abnormal: int) -> int:
    """Turn an observed close code into one a close frame may carry."""
    if code is None or code in (1005, 1006, 1015):
        return abnormal if code == 1006 else 1000
    if code in _SENDABLE_CODES or 3000 <= code <= 4999:
        return code
    return 1011


def _upstream_url(base_url: str, path: str, query: str) -> str:
    scheme_map = {"http://": "ws://", "https://": "wss://"}
    for http_scheme, ws_scheme in scheme_map.items():
        if base_url.startswith(http_scheme):
            base_url = ws_scheme + base_url[len(http_scheme) :]
            break
    return f"{base_url}{path}?{query}" if query else f"{base_url}{path}"


async def _connect(
    websocket: WebSocket, *, app_id: str, slug: str, request_id: str, headers: list[tuple[str, str]]
) -> tuple[UpstreamSocket | None, str, Any]:
    """Resolve + connect with the D5.1 retry. Returns ``(socket, fallback_kind, upstream)``."""
    from websockets.exceptions import InvalidHandshake

    config = get_config()
    path = strip_entry_prefix(websocket.url.path, slug, config.entry_prefix)
    offered = [p.strip() for p in websocket.headers.get("Sec-WebSocket-Protocol", "").split(",") if p.strip()]
    connector = get_upstream_connector()

    for attempt in (0, 1):
        upstream = await resolve_upstream(app_id, refresh=attempt == 1)
        if upstream is None:
            return None, PAGE_RECOVERING, None
        if upstream.starting:
            return None, PAGE_DEPLOYING, upstream
        url = _upstream_url(upstream.base_url, path, websocket.url.query)
        try:
            socket = await connector(url, headers, offered, config.upstream_connect_timeout_seconds)
        except (OSError, TimeoutError) as exc:
            # Stale address: drop the cached entry and resolve once more.
            logger.info(
                "app_proxy.request request_id=%s slug=%s protocol=ws upstream=%s connect_failed=%s attempt=%s",
                request_id,
                slug,
                upstream.base_url,
                exc,
                attempt,
            )
            continue
        except InvalidHandshake as exc:
            # The app answered the upgrade with an HTTP error: no ``/ws`` route,
            # or its own refusal. Its own answer, not a stale address — no retry.
            logger.warning(
                "app_proxy.request request_id=%s slug=%s protocol=ws upstream=%s handshake_rejected=%s",
                request_id,
                slug,
                upstream.base_url,
                exc,
            )
            return None, PAGE_RECOVERING, upstream
        return socket, "", upstream
    return None, PAGE_RECOVERING, None


#: What a pump reports when its direction ends: which side hung up, with the
#: code and reason it observed. A send that fails because the *other* side is
#: gone is reported as that side's closure, so the decision below never has to
#: unpick an exception to learn who left.
PumpEnd = tuple[str, int | None, str]


async def _pump_client_to_upstream(websocket: WebSocket, upstream: UpstreamSocket) -> PumpEnd:
    from websockets.exceptions import ConnectionClosed

    while True:
        try:
            message = await websocket.receive()
        except (WebSocketDisconnect, RuntimeError, OSError, anyio.ClosedResourceError):
            # The server side tore the channel down under us (uvicorn on a
            # dropped TCP connection, the test client on exit): the browser is
            # gone, whatever the protocol layer managed to say about it.
            return "client", None, ""
        if message["type"] == "websocket.disconnect":
            return "client", message.get("code"), message.get("reason") or ""
        try:
            if message.get("text") is not None:
                await upstream.send(message["text"])
            elif message.get("bytes") is not None:
                await upstream.send(message["bytes"])
        except ConnectionClosed:
            return "upstream", upstream.close_code, upstream.close_reason or ""


async def _pump_upstream_to_client(websocket: WebSocket, upstream: UpstreamSocket) -> PumpEnd:
    from websockets.exceptions import ConnectionClosed

    while True:
        try:
            data = await upstream.recv()
        except ConnectionClosed:
            return "upstream", upstream.close_code, upstream.close_reason or ""
        try:
            if isinstance(data, str):
                await websocket.send_text(data)
            else:
                await websocket.send_bytes(data)
        except (WebSocketDisconnect, RuntimeError, OSError):
            return "client", None, ""


async def _reauthorize_loop(websocket: WebSocket, *, slug: str, access_token: str | None, request_id: str) -> Verdict:
    """Invariant ② safety net: re-ask on an interval, return the first non-allow."""
    interval = get_config().ws_reauthorize_interval_seconds
    while True:
        await asyncio.sleep(interval)
        verdict = await authorize(
            slug=slug,
            access_token=access_token,
            request_id=request_id,
            client_ip=websocket.client.host if websocket.client else None,
        )
        if not verdict.allowed:
            return verdict


async def _await_revocation(entry: connections.Connection) -> tuple[int, str]:
    """Resolves when the registry asks this connection to end (invariant ②)."""
    return await asyncio.shield(entry.closed)


async def _close_client(websocket: WebSocket, code: int, reason: str) -> None:
    if websocket.client_state == WebSocketState.CONNECTED and websocket.application_state == WebSocketState.CONNECTED:
        try:
            await websocket.close(code=code, reason=reason)
        except (RuntimeError, WebSocketDisconnect, OSError):
            # Already gone on the client side — nothing left to tell.
            pass


async def _close_upstream(upstream: UpstreamSocket, code: int, reason: str) -> None:
    try:
        await upstream.close(code=code, reason=reason)
    except Exception as exc:
        logger.debug("app_proxy.ws upstream close failed: %s", exc)


async def proxy_websocket(
    websocket: WebSocket,
    *,
    slug: str,
    verdict: Verdict,
    access_token: str | None,
    request_id: str,
) -> None:
    """Everything after "allow" for an upgrade: connect, accept, pump, expire."""
    started = time.monotonic()
    config = get_config()
    app_id = verdict.app_id
    user_id = verdict.material.get("X-BiSheng-User-Id")
    if not app_id:
        logger.error("app_proxy.request request_id=%s slug=%s protocol=ws allow without app_id", request_id, slug)
        await websocket.close(code=ws_close_code(PAGE_RECOVERING))
        return

    log_forged_headers(websocket, request_id, slug)
    headers = [
        (name, value)
        for name, value in upstream_headers_for(websocket, verdict, slug=slug, request_id=request_id)
        if name.lower() not in _HANDSHAKE_HEADERS
    ]

    upstream, fallback, route = await _connect(
        websocket, app_id=app_id, slug=slug, request_id=request_id, headers=headers
    )
    if upstream is None:
        code = ws_close_code(fallback)
        logger.warning(
            "app_proxy.fallback request_id=%s slug=%s protocol=ws kind=%s close_code=%s",
            request_id,
            slug,
            fallback,
            code,
        )
        await websocket.close(code=code)
        return

    lifetime = connection_lifetime(
        obo_expires_at=obo_expiry(verdict, obo_token=verdict.obo_token),
        now=time.time(),
        max_lifetime=verdict.ws_max_lifetime_seconds or config.ws_max_lifetime_seconds,
        jitter=config.ws_lifetime_jitter_seconds,
    )

    try:
        await websocket.accept(subprotocol=upstream.subprotocol)
    except (RuntimeError, WebSocketDisconnect):
        # The browser went away between the handshake request and our accept.
        await _close_upstream(upstream, 1001, "client left")
        return

    entry = connections.registry.register(app_id=app_id, user_id=user_id, slug=slug, request_id=request_id)
    c2u = asyncio.create_task(_pump_client_to_upstream(websocket, upstream), name="ws-c2u")
    u2c = asyncio.create_task(_pump_upstream_to_client(websocket, upstream), name="ws-u2c")
    deadline = asyncio.create_task(asyncio.sleep(lifetime), name="ws-deadline")
    revoked = asyncio.create_task(_await_revocation(entry), name="ws-revoked")
    reauth = asyncio.create_task(
        _reauthorize_loop(websocket, slug=slug, access_token=access_token, request_id=request_id), name="ws-reauth"
    )
    tasks = {c2u, u2c, deadline, revoked, reauth}

    closed_by, code, reason = "proxy", 1011, ""
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        if c2u in done or u2c in done:
            closed_by, observed, reason = (c2u if c2u in done else u2c).result()
            # A browser that vanished is told nothing; an app that vanished is
            # reported to the browser as "nothing answering" (4503, reconnect).
            code = _sendable(observed, abnormal=1001 if closed_by == "client" else ws_close_code(PAGE_RECOVERING))
        elif deadline in done:
            closed_by, code, reason = "expiry", WS_CLOSE_EXPIRED, "authorization expired; reconnect"
        elif revoked in done:
            closed_by = "revocation"
            code, reason = revoked.result()
        elif reauth in done:
            closed_by = "reauthorization"
            flipped = reauth.result()
            code, reason = ws_close_code(flipped.decision), flipped.decision
        else:  # pragma: no cover - a task raised; treat as an internal error
            closed_by = "error"
    except Exception:
        logger.exception("app_proxy.ws request_id=%s slug=%s pump failed", request_id, slug)
    finally:
        connections.registry.unregister(entry)
        for task in tasks:
            if not task.done():
                task.cancel()
        # Both sides hear the same code. Order does not matter for correctness,
        # but closing the browser side first shortens what the visitor sees.
        if closed_by != "client":
            await _close_client(websocket, code, reason)
        if closed_by != "upstream":
            await _close_upstream(upstream, code, reason)
        # Retrieve every outcome, cancelled or failed, so nothing is logged as
        # "Task exception was never retrieved" after the connection is gone.
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info(
            "app_proxy.request request_id=%s slug=%s user_id=%s protocol=ws decision=allow cache_hit=%s "
            "generation=%s lifetime_s=%.0f closed_by=%s close_code=%s reason=%s duration_ms=%.1f",
            request_id,
            slug,
            user_id,
            verdict.cache_hit,
            getattr(route, "generation", None),
            lifetime,
            closed_by,
            code,
            reason,
            (time.monotonic() - started) * 1000,
        )
