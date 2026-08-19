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

import hashlib
import hmac
import json
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

    def __init__(self, secret: str) -> None:
        self.secret = secret
        self.response: dict[str, Any] = allow_response()
        self.status_code = 200
        self.fail: Exception | None = None
        self.calls: list[dict[str, Any]] = []
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
        body = self.response
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

        app_id = request.url.path.rsplit("/", 2)[-2]
        self.calls.append(app_id)
        if self.status_code >= 400:
            response = JSONResponse({"code": "internal_error"}, status_code=self.status_code)
            await response(scope, receive, send)
            return

        queued = self.script.get(app_id)
        route = queued.pop(0) if queued else self.routes.get(app_id)
        if route is None:
            response = JSONResponse({"code": "not_found", "message": "no live instance"}, status_code=404)
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
