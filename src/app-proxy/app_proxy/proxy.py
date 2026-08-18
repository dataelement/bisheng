"""The forward itself: resolve → strip → inject → stream.

Streaming in both directions is not an optimisation here. Hosted apps serve
SSE, long polls and file downloads; buffering a response would turn a live
stream into a stall, and buffering a request would cap uploads at whatever
memory the proxy is willing to hold.

The one retry (D5.1) is narrow on purpose: **connection-level failures only,
exactly once, after invalidating the cached address**. A refused connection
means the address is stale — the container was replaced or died — so asking the
manager again is the fix. A 500 from the app is the app's own answer and is
passed through untouched; retrying it would silently duplicate non-idempotent
requests.
"""

from __future__ import annotations

import logging
import time

import httpx
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from app_proxy.authz import Verdict
from app_proxy.config import get_config
from app_proxy.headers import build_upstream_headers, is_platform_header
from app_proxy.pages import PAGE_HTTP_STATUS, PAGE_RECOVERING, error_payload, json_status, render_page
from app_proxy.routing import entry_prefix_for, resolve_upstream, strip_entry_prefix

logger = logging.getLogger(__name__)

#: Response headers that describe *this* hop and must not be replayed onto the
#: next one. ``content-length`` and ``content-encoding`` are deliberately kept:
#: we forward raw bytes, so the body is exactly what the upstream produced.
_RESPONSE_HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)

_transport: httpx.AsyncBaseTransport | None = None
_client: httpx.AsyncClient | None = None


def set_upstream_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Test / bootstrap seam. Swapping the transport rebuilds the client."""
    global _transport, _client
    _transport = transport
    _client = None


def get_upstream_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        config = get_config()
        _client = httpx.AsyncClient(
            transport=_transport,
            timeout=httpx.Timeout(
                connect=config.upstream_connect_timeout_seconds,
                read=config.upstream_read_timeout_seconds,
                write=config.upstream_read_timeout_seconds,
                pool=config.upstream_connect_timeout_seconds,
            ),
            # A proxy passes redirects to the browser; following them here would
            # hide the app's own navigation and rewrite the URL bar's meaning.
            follow_redirects=False,
        )
    return _client


def _external_proto_and_host(request: Request) -> tuple[str, str]:
    """What the visitor typed, as best we can know it (D5.2).

    ``APP_PROXY_ENTRY_BASE_URL`` wins when configured — that is the only fully
    trustworthy answer and the recommended deployment setting.

    Otherwise the **host** comes from the ``Host`` header and never from
    ``X-Forwarded-Host``: nginx rewrites ``Host`` to the original, while
    ``X-Forwarded-Host`` may be whatever the visitor sent, and an app that
    builds links from a forged host hands out working phishing URLs.

    The **scheme** is the asymmetric case: nginx→app-proxy is plain HTTP on
    loopback, so ``X-Forwarded-Proto`` from the immediate peer is the only
    carrier of "the visitor came over TLS". The documented nginx location
    overwrites it with ``$scheme``; set ``entry_base_url`` where that guarantee
    does not hold.
    """
    config = get_config()
    if config.entry_base_url:
        parsed = httpx.URL(config.entry_base_url)
        return parsed.scheme, parsed.netloc.decode("ascii")

    host = request.headers.get("Host", "")
    proto = request.headers.get("X-Forwarded-Proto", "").split(",")[0].strip() or request.url.scheme
    return proto, host


def _forwarded_for(request: Request) -> str | None:
    existing = request.headers.get("X-Forwarded-For", "").strip()
    peer = request.client.host if request.client else None
    if not peer:
        return existing or None
    return f"{existing}, {peer}" if existing else peer


def _log_forged_headers(request: Request, request_id: str, slug: str) -> None:
    forged = [name for name in request.headers if is_platform_header(name)]
    if forged:
        # §7 asks for this signal by name: a client that sends identity headers
        # is either a misconfigured integration or someone probing AC-32, and
        # both are worth seeing before they become an incident.
        logger.warning(
            "app_proxy.header_strip request_id=%s slug=%s stripped=%s",
            request_id,
            slug,
            ",".join(sorted(forged)),
        )


def _recovering_response(request: Request, request_id: str, app_name: str | None) -> Response:
    """AC-36: the crash / switch window is a page, never a 502.

    Static in this wave — the auto-retrying version is T082. Imported lazily to
    keep :mod:`app_proxy.login_handoff` out of this module's import cycle.
    """
    from app_proxy.login_handoff import is_navigation

    if not is_navigation(request):
        return JSONResponse(error_payload(PAGE_RECOVERING, request_id), status_code=json_status(PAGE_RECOVERING))
    return HTMLResponse(
        render_page(
            PAGE_RECOVERING,
            app_name=app_name,
            square_url=get_config().square_url,
            request_id=request_id,
        ),
        status_code=PAGE_HTTP_STATUS,
    )


async def forward(
    request: Request,
    *,
    slug: str,
    tail: str,
    verdict: Verdict,
    request_id: str,
    started: float | None = None,
) -> Response:
    """Everything after "allow": one hop, at most one re-resolve."""
    started = started if started is not None else time.monotonic()
    config = get_config()
    app_id = verdict.app_id
    if not app_id:
        # The backend allowed a request but told us nothing to forward to. Not
        # a user-visible fault of theirs — render the transient page, log loudly.
        logger.error("app_proxy.request request_id=%s slug=%s allow without app_id", request_id, slug)
        return _recovering_response(request, request_id, verdict.app_name)

    _log_forged_headers(request, request_id, slug)

    upstream_path = strip_entry_prefix(request.url.path, slug, config.entry_prefix)
    proto, host = _external_proto_and_host(request)
    headers = build_upstream_headers(
        request.headers.items(),
        verdict.material,
        slug=slug,
        request_id=request_id,
        obo_token=verdict.obo_token,
        proto=proto,
        host=host,
        app_id=app_id,
        entry_prefix=config.entry_prefix,
    )
    forwarded_for = _forwarded_for(request)
    if forwarded_for:
        headers = [(name, value) for name, value in headers if name.lower() != "x-forwarded-for"]
        headers.append(("X-Forwarded-For", forwarded_for))

    client = get_upstream_client()
    query = request.url.query

    for attempt in (0, 1):
        upstream = await resolve_upstream(app_id, refresh=attempt == 1)
        if upstream is None:
            break

        url = httpx.URL(f"{upstream.base_url}{upstream_path}")
        if query:
            url = url.copy_with(query=query.encode("ascii"))

        try:
            # Only forward a request body when the request actually has one.
            # For a bodyless request (GET/HEAD/most navigations) httpx would
            # still read the ASGI receive channel to drain ``request.stream()``,
            # and that read races Starlette's own disconnect-watcher on the SAME
            # receive channel. The race intermittently delivers a spurious
            # ``http.disconnect`` that cancels ``stream_response`` mid-body, so a
            # large upstream response is silently truncated — a 10 MB hosted-app
            # page dropped its tail on roughly a third of requests. Passing no
            # content leaves the receive channel to the disconnect-watcher alone.
            has_body = bool(request.headers.get("content-length") or request.headers.get("transfer-encoding"))
            outbound = client.build_request(
                request.method,
                url,
                headers=headers,
                content=request.stream() if has_body else None,
            )
            response = await client.send(outbound, stream=True)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            # Stale address: drop the cached entry and resolve once more. Any
            # later failure is the app's problem, not the route table's.
            logger.info(
                "app_proxy.request request_id=%s slug=%s upstream=%s connect_failed=%s attempt=%s",
                request_id,
                slug,
                upstream.base_url,
                exc,
                attempt,
            )
            continue
        except (httpx.HTTPError, RuntimeError) as exc:
            # RuntimeError covers "stream consumed" — a retry after the request
            # body was partially written cannot be replayed honestly.
            logger.warning("app_proxy.request request_id=%s slug=%s upstream_error=%s", request_id, slug, exc)
            break

        logger.info(
            "app_proxy.request request_id=%s slug=%s user_id=%s decision=allow cache_hit=%s "
            "upstream_status=%s generation=%s latency_ms=%.1f",
            request_id,
            slug,
            verdict.material.get("X-BiSheng-User-Id"),
            verdict.cache_hit,
            response.status_code,
            upstream.generation,
            (time.monotonic() - started) * 1000,
        )
        response_headers = [
            (name, value) for name, value in response.headers.multi_items() if name.lower() not in _RESPONSE_HOP_BY_HOP
        ]
        return StreamingResponse(
            response.aiter_raw(),
            status_code=response.status_code,
            headers=dict(response_headers),
            background=BackgroundTask(response.aclose),
        )

    logger.warning(
        "app_proxy.fallback request_id=%s slug=%s kind=recovering prefix=%s",
        request_id,
        slug,
        entry_prefix_for(slug, config.entry_prefix),
    )
    return _recovering_response(request, request_id, verdict.app_name)
