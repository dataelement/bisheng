"""Programmable stand-ins for the three things app-proxy talks to.

Each fake is a real ASGI app reached over ``httpx.ASGITransport``, not a
monkeypatched method. That costs a few lines and buys the two properties the
suite actually depends on:

* the **HMAC signing path runs for real** in every test, so a signing
  regression fails everywhere instead of nowhere;
* the **upstream sees real bytes**, so header strip / injection assertions are
  made against what the hosted app would genuinely receive — the whole point of
  AC-32.

Header names here are written out as literals on purpose. A fake that imported
``app_proxy.headers`` would agree with the implementation by construction and
prove nothing.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import threading
from typing import Any

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

#: What a happy-path ``authorize`` hands back. Chinese values are **raw UTF-8**
#: here: JSON carries them fine and app-proxy is the layer that has to make
#: them latin-1 safe (坑 9). ``test_headers`` also covers the pre-encoded
#: variant, so both backend conventions are pinned.
DEFAULT_HEADER_MATERIAL = {
    "X-BiSheng-User-Id": "42",
    "X-BiSheng-User-Name": "张三",
    "X-BiSheng-Tenant-Id": "1",
    "X-BiSheng-Dept-Id": "BS@d4f1",
    "X-BiSheng-Dept-Name": "研发中心",
    "X-BiSheng-Dept-Path": "毕昇科技/研发中心",
    "X-BiSheng-Subject-Kind": "human",
    "X-BiSheng-App-Id": "app-0001",
}

DEFAULT_APP_ID = "app-0001"
DEFAULT_UPSTREAM = "http://172.20.0.7:8080"

#: What the manager would answer while a deploy is in flight and nothing serves
#: yet — the 409 ``deploying`` envelope reserved in contracts-runtime-manager.md
#: §9. The manager does not emit it today (its deploy is synchronous, so no
#: such window exists); the proxy consumes it so the day it appears the page is
#: 「发布中」 and not 「恢复中」. Programmed into :class:`FakeManager` as a
#: route value without an ``upstream`` so a script can say "starting, starting,
#: then ready" the same way it says "refused, then ready".
DEPLOYING_ROUTE: dict[str, Any] = {"phase": "starting"}


def sign(method: str, path: str, raw_body: bytes, secret: str) -> str:
    """Independent re-implementation of the signing string (not an import)."""
    msg = f"{method.upper()}\n{path}\n".encode() + (raw_body or b"")
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


class FrozenClock:
    """Monotonic clock under test control — TTL assertions without sleeping."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def allow_response(
    *,
    material: dict[str, str] | None = None,
    app_id: str = DEFAULT_APP_ID,
    obo_token: str = "obo.jwt.token",
    app_name: str = "问卷小助手",
    owner_name: str = "李四",
) -> dict[str, Any]:
    headers = dict(DEFAULT_HEADER_MATERIAL if material is None else material)
    headers.setdefault("X-BiSheng-App-Id", app_id)
    return {
        "decision": "allow",
        "headers": headers,
        "obo_token": obo_token,
        "app_state": "online",
        "app_id": app_id,
        "app_name": app_name,
        "owner_name": owner_name,
    }


def deny_response(
    decision: str,
    *,
    app_name: str | None = "问卷小助手",
    owner_name: str | None = "李四",
    app_state: str | None = None,
) -> dict[str, Any]:
    """A non-allow verdict.

    ``not_found`` carries no app name or owner by construction — leaking either
    would defeat the "draft / pending / deleted / never existed look identical"
    rule (AC-29).
    """
    if decision == "not_found":
        app_name = owner_name = None
    return {
        "decision": decision,
        "headers": {},
        "obo_token": None,
        "app_state": app_state,
        "app_name": app_name,
        "owner_name": owner_name,
    }


class FakeBackend:
    """The internal authorize endpoint.

    Knobs: :attr:`response` (verdict to hand back), :attr:`status_code`
    (simulate 5xx), :attr:`fail` (simulate a transport error / timeout).
    :attr:`calls` is what the cache assertions count.
    """

    path = "/api/v1/internal/app-proxy/authorize"
    preview_path = "/api/v1/internal/app-proxy/authorize-preview"

    def __init__(self, secret: str) -> None:
        self.secret = secret
        self.response: dict[str, Any] = allow_response()
        #: Verdict for ``authorize-preview``. ``None`` means "answer with
        #: :attr:`response`", which keeps every existing test unchanged; a test
        #: about the preview entry sets it explicitly.
        self.preview_response: dict[str, Any] | None = None
        self.status_code = 200
        self.fail: Exception | None = None
        self.calls: list[dict[str, Any]] = []
        #: Paths the fake was asked for, so a test can prove the *preview*
        #: endpoint was called and not the application one.
        self.paths: list[str] = []
        #: When true, wrap the body in the platform's ``{status_code, data}``
        #: envelope — the endpoint may end up going through resp_200().
        self.envelope = False

    async def __call__(self, scope, receive, send) -> None:
        request = Request(scope, receive)
        raw = await request.body()
        if self.fail is not None:
            raise self.fail
        expected = sign(request.method, request.url.path, raw, self.secret)
        provided = request.headers.get("X-Signature", "")
        if not hmac.compare_digest(expected, provided):
            response: Response = JSONResponse({"detail": "bad signature"}, status_code=401)
            await response(scope, receive, send)
            return
        self.calls.append(json.loads(raw) if raw else {})
        self.paths.append(request.url.path)
        body = self.response
        if request.url.path == self.preview_path and self.preview_response is not None:
            body = self.preview_response
        if self.envelope:
            body = {"status_code": 200, "status_message": "SUCCESS", "data": body}
        response = JSONResponse(body, status_code=self.status_code)
        await response(scope, receive, send)


class FakeManager:
    """The runtime-manager route endpoint.

    :attr:`script` turns a single app_id into a queue of answers so a test can
    say "first call fails, second succeeds" — which is exactly the D5.1
    invalidate-and-retry-once path.
    """

    def __init__(self, secret: str) -> None:
        self.secret = secret
        self.routes: dict[str, dict[str, Any] | None] = {
            DEFAULT_APP_ID: {"upstream": DEFAULT_UPSTREAM, "version_id": "v1", "generation": 1},
        }
        self.script: dict[str, list[dict[str, Any] | None]] = {}
        self.status_code = 200
        self.fail: Exception | None = None
        self.calls: list[str] = []
        self.paths: list[str] = []

    async def __call__(self, scope, receive, send) -> None:
        request = Request(scope, receive)
        raw = await request.body()
        if self.fail is not None:
            raise self.fail
        expected = sign(request.method, request.url.path, raw, self.secret)
        if not hmac.compare_digest(expected, request.headers.get("X-Signature", "")):
            response: Response = JSONResponse({"detail": "bad signature"}, status_code=401)
            await response(scope, receive, send)
            return

        # ``/v1/apps/{id}/route`` and ``/v1/previews/{id}/route`` both put the
        # id in the same position, so one expression serves both.
        app_id = request.url.path.rsplit("/", 2)[-2]
        self.calls.append(app_id)
        self.paths.append(request.url.path)
        if self.status_code >= 400:
            response = JSONResponse({"code": "internal_error"}, status_code=self.status_code)
            await response(scope, receive, send)
            return

        queued = self.script.get(app_id)
        route = queued.pop(0) if queued else self.routes.get(app_id)
        if route is None:
            response = JSONResponse({"code": "not_found", "message": "no live instance"}, status_code=404)
        elif not route.get("upstream"):
            # The reserved shape for an in-flight deploy: an error envelope, not
            # a route (contracts-runtime-manager.md §9 — see DEPLOYING_ROUTE).
            response = JSONResponse(
                {"detail": {"code": "deploying", "message": "a deploy is in flight", "phase": "starting"}},
                status_code=409,
            )
        else:
            response = JSONResponse(route)
        await response(scope, receive, send)


class EchoUpstream:
    """A hosted app that reports exactly what reached it.

    Returns ``{method, path, query, headers: [[name, value], ...], body}``.
    Header pairs stay a list, not a dict: duplicates and casing are part of
    what the strip tests assert.
    """

    def __init__(self) -> None:
        self.status_code = 200
        self.requests: list[dict[str, Any]] = []
        #: Bytes to stream back in chunks — used by the streaming passthrough test.
        self.stream_chunks: list[bytes] | None = None
        #: Extra response headers as raw pairs, so a test can send the SAME name
        #: twice (``Set-Cookie``) — the case a Mapping cannot express.
        self.response_headers: list[tuple[bytes, bytes]] = []

    async def __call__(self, scope, receive, send) -> None:
        request = Request(scope, receive)
        body = await request.body()
        record = {
            "method": request.method,
            "path": request.url.path,
            "query": request.url.query,
            "headers": [[k.decode("latin-1"), v.decode("latin-1")] for k, v in scope["headers"]],
            "body": body.decode("utf-8", "replace"),
        }
        self.requests.append(record)

        if self.stream_chunks is not None:
            await send(
                {
                    "type": "http.response.start",
                    "status": self.status_code,
                    "headers": [(b"content-type", b"application/octet-stream"), *self.response_headers],
                }
            )
            for chunk in self.stream_chunks:
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
            await send({"type": "http.response.body", "body": b"", "more_body": False})
            return

        response = JSONResponse(record, status_code=self.status_code)
        response.raw_headers.extend(self.response_headers)
        await response(scope, receive, send)


class UpstreamTransport(httpx.AsyncBaseTransport):
    """Routes ``http://host:port`` to an ASGI app — or refuses the connection.

    ``refuse`` is how the suite reproduces the case D5.1 is written for: a
    cached upstream address that no longer answers because the container was
    replaced or died.
    """

    def __init__(self, apps: dict[str, Any] | None = None) -> None:
        self.apps: dict[str, Any] = apps or {}
        self.refuse: set[str] = set()
        self.attempts: list[str] = []

    def register(self, base_url: str, app: Any) -> None:
        self.apps[base_url.rstrip("/")] = app

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        origin = f"{request.url.scheme}://{request.url.netloc.decode('ascii')}"
        self.attempts.append(origin)
        if origin in self.refuse:
            raise httpx.ConnectError("connection refused", request=request)
        app = self.apps.get(origin)
        if app is None:
            raise httpx.ConnectError(f"no route to {origin}", request=request)
        return await httpx.ASGITransport(app=app).handle_async_request(request)


class WsEchoUpstream:
    """A hosted app speaking WebSocket, on a real loopback port.

    Not an in-memory stub: the proxy's real ``websockets`` client performs a
    real handshake against it, so what :attr:`handshakes` records is exactly
    what a hosted app would see — the whole point of the strip / inject
    assertions (AC-32), same as :class:`EchoUpstream` for HTTP.

    Runs on its own thread with its own event loop because ``TestClient`` drives
    the proxy from a portal thread of its own; the two must not share a loop.

    Frames are echoed back. A text frame ``close:<code>:<reason>`` makes the
    server close the connection with that code — how the suite drives
    "upstream hangs up" without a second control channel.
    """

    def __init__(self) -> None:
        self.handshakes: list[dict[str, Any]] = []
        #: Subprotocols the app is willing to speak; the first one the client
        #: offers that is in here wins (RFC 6455 §4.2.2 order).
        self.subprotocols: list[str] = ["chat", "json"]
        #: When set, the handshake is refused with this HTTP status.
        self.reject_status: int | None = None
        self.port: int = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._stop: asyncio.Event | None = None

    # -- lifecycle -----------------------------------------------------
    def start(self) -> WsEchoUpstream:
        self._thread = threading.Thread(target=self._run, name="ws-echo-upstream", daemon=True)
        self._thread.start()
        if not self._ready.wait(5):  # pragma: no cover - only on a wedged host
            raise RuntimeError("WsEchoUpstream did not start")
        return self

    def stop(self) -> None:
        if self._loop is not None and self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
        if self._thread is not None:
            self._thread.join(5)

    def _run(self) -> None:
        asyncio.run(self._main())

    async def _main(self) -> None:
        from websockets.asyncio.server import serve

        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        async with serve(
            self._handler,
            "127.0.0.1",
            0,
            subprotocols=self.subprotocols,
            select_subprotocol=self._select_subprotocol,
            process_request=self._process_request,
        ) as server:
            self.port = server.sockets[0].getsockname()[1]
            self._ready.set()
            await self._stop.wait()

    # -- protocol --------------------------------------------------------
    def _select_subprotocol(self, connection, offered):
        """First offered protocol the app speaks; none offered is fine too —
        a real app does not fail the handshake over an absent header."""
        for candidate in offered:
            if candidate in self.subprotocols:
                return candidate
        return None

    async def _process_request(self, connection, request):
        if self.reject_status is not None:
            from http import HTTPStatus

            return connection.respond(HTTPStatus(self.reject_status), "refused by the app\n")
        return None

    async def _handler(self, connection) -> None:
        from websockets.exceptions import ConnectionClosed

        record: dict[str, Any] = {
            "path": connection.request.path,
            "headers": [[k, v] for k, v in connection.request.headers.raw_items()],
            "subprotocol": connection.subprotocol,
            "close_code": None,
        }
        self.handshakes.append(record)
        try:
            async for message in connection:
                if isinstance(message, str) and message.startswith("close:"):
                    _, code, reason = message.split(":", 2)
                    await connection.close(int(code), reason)
                    break
                await connection.send(message)
        except ConnectionClosed:
            pass
        finally:
            await connection.wait_closed()
            record["close_code"] = connection.close_code

    @property
    def base_url(self) -> str:
        return f"ws://127.0.0.1:{self.port}"


class WsUpstreamTransport:
    """The WebSocket twin of :class:`UpstreamTransport`: origin → real server, or refuse.

    Plugged in through ``app_proxy.websocket.set_upstream_connector``. It
    rewrites only the authority of the URL the proxy built and hands the rest
    (path, query, headers, subprotocols) to the real client, so the proxy's
    own URL construction is what gets exercised.
    """

    def __init__(self) -> None:
        self.servers: dict[str, WsEchoUpstream] = {}
        self.refuse: set[str] = set()
        self.attempts: list[str] = []

    def register(self, base_url: str, server: WsEchoUpstream) -> None:
        self.servers[base_url.rstrip("/").replace("http://", "ws://").replace("https://", "wss://")] = server

    async def __call__(self, url: str, headers: list[tuple[str, str]], subprotocols: list[str], timeout: float):
        from urllib.parse import urlsplit, urlunsplit

        from websockets.asyncio.client import connect

        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        self.attempts.append(origin)
        if origin in self.refuse:
            raise OSError(f"connection refused: {origin}")
        server = self.servers.get(origin)
        if server is None:
            raise OSError(f"no route to {origin}")
        real = urlunsplit(("ws", f"127.0.0.1:{server.port}", parts.path, parts.query, ""))
        return await connect(
            real,
            additional_headers=headers,
            subprotocols=subprotocols or None,
            open_timeout=timeout,
            proxy=None,
            max_size=None,
        )


#: A preview session id shaped like the one the platform mints (uuid4 hex).
DEFAULT_PREVIEW_SESSION = "2f1c8d4ab0e5461d9a77c3e5d8b21f40"


def preview_allow_response(
    *,
    session: str = DEFAULT_PREVIEW_SESSION,
    material: dict[str, str] | None = None,
    app_id: str = DEFAULT_APP_ID,
    obo_token: str = "obo.preview.token",
) -> dict[str, Any]:
    """What ``authorize-preview`` hands back for the approver it belongs to.

    Note what is **absent**: no ``owner_name``. A preview refusal must not name
    anybody — the visitor has not been told the application exists.
    """
    headers = dict(DEFAULT_HEADER_MATERIAL if material is None else material)
    headers.setdefault("X-BiSheng-App-Id", app_id)
    return {
        "decision": "allow",
        "headers": headers,
        "obo_token": obo_token,
        "app_state": "draft",
        "app_id": app_id,
        "app_name": "问卷小助手",
        "preview_session": session,
    }
