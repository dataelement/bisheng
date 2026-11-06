"""The `bisheng dev` mini reverse proxy: identity in, forged identity out (T042).

This is the local twin of F054's app-proxy (`src/app-proxy/app_proxy/headers.py`)
and it exists so that the code an application writes to read its visitor is the
**same code** locally and hosted (AC-23, INV-32). Three things it copies from
app-proxy on purpose, and a contract test (`tests/test_platform_contract.py`)
reads that file with `ast` to make sure they cannot drift:

* **The strip is a normalised prefix match, never a name list.** Normalise
  (`lower()` + `_` → `-`), then drop everything under `x-bisheng-`. This is the
  CVE-2025-64484 lesson: oauth2-proxy stripped the exact hyphenated spellings it
  knew about, and `X_Forwarded_User` walked straight past it because WSGI-family
  frameworks fold underscores and hyphens onto one key (AC-25).
* **The ten canonical injected names, in the same order.** Absent material is
  omitted, never emitted empty, so `if request.headers.get("X-BiSheng-Dept-Id")`
  means the same thing in both places. A service account has no department, so
  the three `Dept-*` headers are simply not there under `dev`.
* **The per-request short-lived credential handle** (`X-BiSheng-Access-Token`).
  Hosted, app-proxy injects an OBO token the backend signs (F054 AC-34, 900 s).
  Locally there is no backend signer to ask and — as of this round — no
  consumer either, so the handle is **minted locally**: an opaque, HMAC-signed,
  15-minute token bound to this `dev` session. What matters for AC-23 is the
  shape (a fresh short-lived handle per request, in the same header) and one
  invariant this module guards with a test: **the login key never appears in
  any header and never enters the application process.**

What it does *not* do: proxy platform-capability calls (spec 决议-3 — the app
talks to the platform directly, the same way it does hosted), or accept any
`--as` / identity override (AC-25; `cli.py` has no such flag and
`tests/test_cli.py::test_no_as_flag_anywhere` keeps it that way).

Dependency budget (design D12): the listener is the standard library's
`ThreadingHTTPServer`; the upstream hop reuses `httpx`, which the CLI already
carries. No third entry.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import secrets
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from bisheng_cli.output import Emitter

#: Normalised prefix owned by the platform. Everything under it is ours to write
#: and no one else's to send — the equivalence class app-proxy strips.
PLATFORM_HEADER_PREFIX = "x-bisheng-"

#: The ten of F054 design §4.2 ③, in the order they go on the wire. Mirrors
#: `app_proxy.headers.INJECTED_HEADER_NAMES` verbatim (contract-tested).
INJECTED_HEADER_NAMES: tuple[str, ...] = (
    "X-BiSheng-User-Id",
    "X-BiSheng-User-Name",
    "X-BiSheng-Tenant-Id",
    "X-BiSheng-Dept-Id",
    "X-BiSheng-Dept-Name",
    "X-BiSheng-Dept-Path",
    "X-BiSheng-Subject-Kind",
    "X-BiSheng-App-Id",
    "X-BiSheng-Access-Token",
    "X-BiSheng-Request-Id",
)

_CANONICAL_BY_NORMALISED = {name.lower(): name for name in INJECTED_HEADER_NAMES}

#: Dropped outright before forwarding — same set as app-proxy, same reasons:
#: `x-forwarded-*` / `forwarded` are rewritten by the proxy; hop-by-hop headers
#: are RFC 9110 §7.6.1; `host` / `content-length` are recomputed for the
#: upstream request.
DROPPED_HEADERS = frozenset(
    {
        "x-forwarded-prefix",
        "x-forwarded-proto",
        "x-forwarded-host",
        "x-forwarded-port",
        "forwarded",
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "proxy-connection",
        "te",
        "trailer",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "host",
        "content-length",
    }
)

#: The platform session cookie app-proxy removes from `Cookie` (K7): the browser
#: sends it host-only, so under `dev` it only shows up when the platform itself
#: is on localhost — but that is exactly the case where forwarding it would hand
#: the app a credential far stronger than the scoped handle it is meant to get.
PLATFORM_SESSION_COOKIE = "access_token_cookie"

#: Hop-by-hop response headers not relayed back to the browser.
_RESPONSE_DROPPED = frozenset(
    {"connection", "keep-alive", "transfer-encoding", "content-length", "upgrade", "te", "trailer"}
)

#: Same lifetime as the hosted OBO token (F054 AC-34).
HANDLE_TTL_SECONDS = 900
HANDLE_PREFIX = "bsdev"

_CONTROL_CHARS = frozenset(chr(i) for i in range(0x20)) | {chr(0x7F)}


# ---- header helpers (mirrors of app_proxy.headers) ---------------------------


def normalize_header_name(name: str) -> str:
    """``X_BiSheng_User_Id`` and ``X-BiSheng-User-Id`` are the same header."""
    return name.strip().lower().replace("_", "-")


def is_platform_header(name: str) -> bool:
    return normalize_header_name(name).startswith(PLATFORM_HEADER_PREFIX)


def encode_header_value(value: str) -> str:
    """Make a value latin-1 safe without ever double-encoding it.

    ASCII in, ASCII out — so a value that is already percent-encoded survives
    unchanged. Control characters are encoded even when ASCII: a raw CR/LF in a
    header value is a response-splitting primitive.
    """
    text = str(value)
    if text.isascii() and not (_CONTROL_CHARS & set(text)):
        return text
    return quote(text, safe="/")


def _filter_cookie(value: str, session_cookie_name: str) -> str:
    kept = []
    for chunk in value.split(";"):
        pair = chunk.strip()
        if not pair:
            continue
        name = pair.split("=", 1)[0].strip()
        if name == session_cookie_name:
            continue
        kept.append(pair)
    return "; ".join(kept)


def strip_platform_headers(
    headers: Iterable[tuple[str, str]],
    *,
    session_cookie_name: str = PLATFORM_SESSION_COOKIE,
    strip_session_cookie: bool = True,
) -> list[tuple[str, str]]:
    """Everything the client sent, minus what it must not be able to say (AC-25)."""
    kept: list[tuple[str, str]] = []
    for name, value in headers:
        normalised = normalize_header_name(name)
        if normalised.startswith(PLATFORM_HEADER_PREFIX):
            continue
        if normalised in DROPPED_HEADERS:
            continue
        if normalised == "cookie" and strip_session_cookie:
            filtered = _filter_cookie(value, session_cookie_name)
            if not filtered:
                continue
            kept.append((name, filtered))
            continue
        kept.append((name, value))
    return kept


# ---- identity -----------------------------------------------------------------


@dataclass(frozen=True)
class DevIdentity:
    """What `dev` injects: the logged-in credential's subject, nothing else.

    Built from the platform's fresh `whoami` answer at start-up rather than the
    stored snapshot, so a renamed or re-owned account shows up on the next
    `dev`, and so a revoked key is refused before anything is injected (AC-29).
    """

    user_id: str
    user_name: str
    tenant_id: str | None
    subject_kind: str
    app_id: str | None = None

    @classmethod
    def from_whoami(cls, whoami: Mapping[str, Any], *, app_id: str | None = None) -> DevIdentity:
        # The hosted side spells a natural person `human` (entry_authz_service
        # `_user_facts`); a `bs-pat-` personal token therefore maps to that,
        # and a service-account key to `service_account` — the kind AC-23 names.
        kind = "human" if whoami.get("actor_kind") == "natural_person" else "service_account"
        tenant = whoami.get("tenant_id")
        return cls(
            user_id=str(whoami.get("actor_id") if whoami.get("actor_id") is not None else ""),
            user_name=str(whoami.get("actor_name") or ""),
            tenant_id=str(tenant) if tenant is not None else None,
            subject_kind=kind,
            app_id=app_id or None,
        )

    def material(self) -> dict[str, str]:
        """Canonical header → value, absent values omitted (never emitted empty)."""
        values = {
            "X-BiSheng-User-Id": self.user_id,
            "X-BiSheng-User-Name": encode_header_value(self.user_name),
            "X-BiSheng-Tenant-Id": self.tenant_id or "",
            "X-BiSheng-Subject-Kind": self.subject_kind,
            "X-BiSheng-App-Id": self.app_id or "",
        }
        return {name: value for name, value in values.items() if value}


class HandleMinter:
    """Mints the per-request short-lived credential handle (AC-23).

    The secret is generated per `dev` session and never written anywhere, so a
    handle is meaningful only to this process — which is the whole point: it
    is a *handle* with the hosted token's shape and lifetime, not a credential
    that reaches the platform. `verify` exists so a test (or a future local
    consumer) can check the signature and expiry rather than trusting bytes.
    """

    def __init__(
        self, identity: DevIdentity, *, ttl_seconds: int = HANDLE_TTL_SECONDS, now: Callable[[], float] = time.time
    ) -> None:
        self._identity = identity
        self._ttl = ttl_seconds
        self._now = now
        self._secret = secrets.token_bytes(32)

    def mint(self, request_id: str) -> str:
        issued = int(self._now())
        payload = {
            "sub": {
                "app_id": self._identity.app_id,
                "user_id": self._identity.user_id,
                "tenant_id": self._identity.tenant_id,
                "subject_kind": self._identity.subject_kind,
            },
            "iat": issued,
            "exp": issued + self._ttl,
            "rid": request_id,
            "iss": "bisheng-dev",
        }
        body = _b64(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        return f"{HANDLE_PREFIX}.{body}.{self._sign(body)}"

    def verify(self, handle: str) -> dict[str, Any] | None:
        try:
            prefix, body, signature = handle.split(".")
        except ValueError:
            return None
        if prefix != HANDLE_PREFIX or not hmac.compare_digest(signature, self._sign(body)):
            return None
        payload = json.loads(_unb64(body))
        if payload.get("exp", 0) < self._now():
            return None
        return payload

    def _sign(self, body: str) -> str:
        return _b64(hmac.new(self._secret, body.encode("ascii"), hashlib.sha256).digest())


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# ---- building the upstream request ------------------------------------------


def build_injected_headers(
    identity: DevIdentity,
    *,
    request_id: str,
    handle: str | None,
    proto: str = "http",
    host: str = "",
    prefix: str = "",
) -> list[tuple[str, str]]:
    """The ten identity headers plus the three forwarding headers we own.

    `X-Forwarded-Prefix` carries the same `/apps/{slug}` the hosted proxy sends,
    and `BISHENG_APP_BASE_PATH` holds the same value (see `DevProxy`).
    """
    values: dict[str, str] = {}
    for raw_name, raw_value in identity.material().items():
        canonical = _CANONICAL_BY_NORMALISED.get(normalize_header_name(raw_name))
        if canonical is None or raw_value is None or str(raw_value) == "":
            continue
        values[canonical] = str(raw_value)
    if handle:
        values["X-BiSheng-Access-Token"] = handle
    values["X-BiSheng-Request-Id"] = request_id

    injected = [(name, encode_header_value(values[name])) for name in INJECTED_HEADER_NAMES if name in values]
    injected.append(("X-Forwarded-Prefix", prefix))
    if proto:
        injected.append(("X-Forwarded-Proto", proto))
    if host:
        injected.append(("X-Forwarded-Host", host))
    return injected


def build_upstream_headers(
    inbound: Iterable[tuple[str, str]],
    identity: DevIdentity,
    *,
    request_id: str,
    handle: str | None,
    proto: str = "http",
    host: str = "",
    prefix: str = "",
) -> list[tuple[str, str]]:
    """Strip then inject, in that order — the only order that is safe."""
    return strip_platform_headers(inbound) + build_injected_headers(
        identity, request_id=request_id, handle=handle, proto=proto, host=host, prefix=prefix
    )


# ---- the entry prefix -----------------------------------------------------------

#: The platform's entry segment. Hosted, every app lives at `/apps/{slug}`.
ENTRY_PREFIX = "/apps"


def entry_prefix_for(slug: str, entry_prefix: str = ENTRY_PREFIX) -> str:
    return f"{entry_prefix.rstrip('/')}/{slug}"


def restore_entry_prefix(location: str, slug: str, entry_prefix: str = ENTRY_PREFIX, upstream_base: str = "") -> str:
    """Put the prefix back on a redirect the app sent — a copy of app-proxy's.

    `tests/test_platform_contract.py` runs both implementations over the same
    cases, so the redirect an app sends lands in the same place locally and
    hosted. See `app_proxy.routing.restore_entry_prefix` for the rule.
    """
    prefix = entry_prefix_for(slug, entry_prefix)
    value = location
    if upstream_base and "://" in value:
        target, origin = urlsplit(value), urlsplit(upstream_base)
        if (target.scheme, target.netloc) != (origin.scheme, origin.netloc):
            return location
        value = target.path or "/"
        if target.query:
            value += "?" + target.query
        if target.fragment:
            value += "#" + target.fragment
    if not value.startswith("/") or value.startswith("//"):
        return location
    if value == prefix or value.startswith((prefix + "/", prefix + "?", prefix + "#")):
        return value
    if value.startswith(entry_prefix.rstrip("/") + "/"):
        return value
    return prefix + value


def outside_prefix_page(path: str, prefix: str) -> str:
    """The 404 body for a request that left the app's prefix.

    Hosted, the same request reaches the platform instead of the app, and the
    developer sees a platform page or a bare 404 with nothing pointing at the
    cause. Here the cause is known, so it is named.
    """
    shown = html.escape(path)
    root = html.escape(prefix)
    return (
        "<!doctype html><meta charset='utf-8'><title>请求离开了应用的路径前缀</title>"
        "<body style='font-family:system-ui,sans-serif;max-width:46rem;margin:3rem auto;line-height:1.6'>"
        f"<h1 style='font-size:1.25rem'>这个请求不在应用的路径前缀 {root}/ 下</h1>"
        f"<p>请求路径：<code>{shown}</code></p>"
        f"<p>托管到平台后，应用挂在 <code>{root}/</code> 下。这个请求会落到平台自己的 "
        f"<code>{shown}</code>，而不是你的应用，所以在线上同样会失败。</p>"
        "<p>原因通常是代码或构建产物里写了以 <code>/</code> 开头的绝对路径，例如 "
        '<code>&lt;img src="/logo.png"&gt;</code>、<code>fetch("/api/x")</code>，'
        "或者前端构建工具的 base 用了默认的 <code>/</code>。</p>"
        "<p>改法：经环境变量 <code>BISHENG_APP_BASE_PATH</code> 拼接链接，或者改用相对路径"
        "（<code>logo.png</code>、<code>api/x</code>）；Vite 把 <code>base</code> 设为 <code>'./'</code>。</p>"
        f"<p><a href='{root}/'>打开应用 {root}/</a></p>"
        "</body>"
    )


# ---- the proxy ----------------------------------------------------------------


def _response_body(response: httpx.Response) -> Iterable[bytes]:
    """Stream the upstream body; fall back to the buffered content.

    A response whose content httpx already holds in memory (a mock transport,
    or a body read during redirect handling) reports its stream as consumed;
    the bytes are still there and are relayed as one chunk.
    """
    if response.is_stream_consumed:
        yield response.content
        return
    yield from response.iter_raw()


@dataclass
class ProxiedResponse:
    status: int
    headers: list[tuple[str, str]]
    body: Iterable[bytes]
    close: Callable[[], None] = lambda: None


class DevProxy:
    """One listener in front of the app process; forwards over a local httpx client.

    `forward` is the whole logic and takes plain values so it can be exercised
    with an `httpx.MockTransport`; the `BaseHTTPRequestHandler` shell around it
    only reads bytes off the socket and writes them back.
    """

    def __init__(
        self,
        *,
        identity: DevIdentity,
        minter: HandleMinter,
        app_port: int,
        listen_port: int,
        listen_host: str = "127.0.0.1",
        emitter: Emitter | None = None,
        transport: httpx.BaseTransport | None = None,
        request_id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
        slug: str = "dev",
    ) -> None:
        self.identity = identity
        # Served under the same `/apps/{slug}` as hosted, prefix stripped on the
        # way in and announced in `X-Forwarded-Prefix`. A root-absolute link
        # (`/logo.png`) then fails here, with a page that names the cause,
        # instead of working locally and 404ing only once deployed.
        self.slug = slug
        self.prefix = entry_prefix_for(slug)
        self._warned_paths: set[str] = set()
        self.minter = minter
        self.app_port = app_port
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.emitter = emitter
        self._request_id_factory = request_id_factory
        self._client = httpx.Client(
            base_url=f"http://127.0.0.1:{app_port}",
            transport=transport,
            trust_env=False,
            # A dev server must not time out a slow first request or an SSE
            # stream; connect stays short so "app not listening" is prompt.
            timeout=httpx.Timeout(None, connect=3.0),
        )
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # -- core ------------------------------------------------------------

    def forward(
        self,
        method: str,
        path: str,
        inbound: list[tuple[str, str]],
        body: bytes,
        *,
        host: str = "",
    ) -> ProxiedResponse:
        raw_path, _, query = path.partition("?")
        suffix = f"?{query}" if query else ""
        if raw_path == self.prefix and method in ("GET", "HEAD"):
            # app-proxy answers the bare prefix the same way: relative links in
            # the page only resolve inside the app with the trailing slash.
            return self._redirect(308, f"{self.prefix}/{suffix}")
        if raw_path == self.prefix:
            upstream_path = "/" + suffix
        elif raw_path.startswith(self.prefix + "/"):
            upstream_path = raw_path[len(self.prefix) :] + suffix
        else:
            return self._outside_prefix(method, raw_path)

        request_id = self._request_id_factory()
        headers = build_upstream_headers(
            inbound,
            self.identity,
            request_id=request_id,
            handle=self.minter.mint(request_id),
            proto="http",
            host=host,
            prefix=self.prefix,
        )
        started = time.monotonic()
        try:
            request = self._client.build_request(method, upstream_path, headers=headers, content=body)
            response = self._client.send(request, stream=True)
        except httpx.ConnectError:
            return self._error(
                502,
                f"应用尚未在 127.0.0.1:{self.app_port} 监听。进程可能还在启动；"
                f"若一直如此，检查应用是否读取了 PORT 环境变量并绑定 0.0.0.0。",
            )
        except httpx.HTTPError as exc:
            return self._error(502, f"转发到应用失败：{exc.__class__.__name__}")

        if self.emitter is not None:
            elapsed = int((time.monotonic() - started) * 1000)
            self.emitter.info(f"{method} {path} → {response.status_code} {elapsed}ms")
        upstream_base = str(self._client.base_url).rstrip("/")
        relayed = [
            (name, restore_entry_prefix(value, self.slug, upstream_base=upstream_base))
            if name.lower() == "location"
            else (name, value)
            for name, value in response.headers.multi_items()
            if name.lower() not in _RESPONSE_DROPPED
        ]
        return ProxiedResponse(
            status=response.status_code,
            headers=relayed,
            body=_response_body(response),
            close=response.close,
        )

    def _redirect(self, status: int, location: str) -> ProxiedResponse:
        return ProxiedResponse(status=status, headers=[("Location", location), ("Content-Length", "0")], body=iter([]))

    def _outside_prefix(self, method: str, path: str) -> ProxiedResponse:
        # Not redirected, not even `/`: a link to `/` in the app is the same
        # defect as any other root-absolute link, and the page below carries a
        # link to the app for the habitual first visit to `127.0.0.1:<port>/`.
        # The browser asks for /favicon.ico at the origin root by itself;
        # hosted it gets the platform's icon, which is not a defect.
        if path not in ("/", "/favicon.ico") and path not in self._warned_paths and self.emitter is not None:
            self._warned_paths.add(path)
            self.emitter.warn(
                f"{method} {path} 不在应用前缀 {self.prefix}/ 下，托管后会落到平台而不是应用（返回 404）。"
                "检查代码或构建产物里以 / 开头的绝对路径。"
            )
        payload = outside_prefix_page(path, self.prefix).encode("utf-8")
        return ProxiedResponse(
            status=404,
            headers=[("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(payload)))],
            body=iter([payload]),
        )

    def _error(self, status: int, text: str) -> ProxiedResponse:
        if self.emitter is not None:
            self.emitter.warn(text)
        payload = text.encode("utf-8")
        return ProxiedResponse(
            status=status,
            headers=[("Content-Type", "text/plain; charset=utf-8")],
            body=iter([payload]),
        )

    # -- lifecycle -------------------------------------------------------

    def start(self) -> None:
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: Any) -> None:
                return  # the proxy prints its own one-liner per request

            def _relay(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                inbound = list(self.headers.items())
                result = proxy.forward(self.command, self.path, inbound, body, host=self.headers.get("Host") or "")
                try:
                    self.send_response(result.status)
                    for name, value in result.headers:
                        self.send_header(name, value)
                    # Body is delimited by connection close: no re-framing, and
                    # streaming responses (SSE) flow through chunk by chunk.
                    self.send_header("Connection", "close")
                    self.end_headers()
                    for chunk in result.body:
                        if chunk:
                            self.wfile.write(chunk)
                            self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass  # the browser went away mid-response; nothing to report
                finally:
                    result.close()
                    self.close_connection = True

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_HEAD = _relay

        self._server = ThreadingHTTPServer((self.listen_host, self.listen_port), Handler)
        self._server.daemon_threads = True
        self.listen_port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, name="bisheng-dev-proxy", daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        """Where to open the app: the listener plus the app's prefix."""
        return f"http://{self.listen_host}:{self.listen_port}{self.prefix}/"

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        self._client.close()
