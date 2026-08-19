"""ASGI entry point. ``uvicorn app_proxy.main:app --host 127.0.0.1 --port 8090``.

Route surface is deliberately tiny:

* ``/healthz`` — liveness for systemd / compose. Answers without touching a
  peer, so a backend outage does not get the proxy restarted.
* ``/apps/{slug}`` and ``/apps/{slug}/{tail}`` — everything else.

Nothing else is served. This process must never become a place where platform
functionality accretes (D5-C).

The request handler below is the whole control flow, in order, in one function
on purpose: validate the slug locally → ask for a verdict → render a page or
forward. Splitting it across modules is what hid the ordering in the designs we
rejected, and the ordering *is* the security property (spec §3).
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.websockets import WebSocket

from app_proxy import clients
from app_proxy.authz import (
    DECISION_ALLOW,
    DECISION_LOGIN,
    DECISION_NOT_FOUND,
    Verdict,
    authorize,
    extract_access_token,
    is_valid_slug,
)
from app_proxy.config import get_config
from app_proxy.login_handoff import (
    WS_CLOSE_NOT_IMPLEMENTED,
    is_navigation,
    render_login_handoff,
    ws_close_code,
)
from app_proxy.pages import PAGE_HTTP_STATUS, error_payload, json_status, render_page
from app_proxy.routing import entry_prefix_for

logger = logging.getLogger(__name__)

ENTRY_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = get_config()
    if not config.backend_secret or not config.manager_secret:
        # Loud, but not fatal: the process still starts and renders its
        # fail-closed page, which is a better failure mode on a half-configured
        # host than a crash loop that takes /apps/* to 502.
        logger.error(
            "app-proxy starting with an unconfigured HMAC secret (backend=%s manager=%s); "
            "every request will fail closed",
            bool(config.backend_secret),
            bool(config.manager_secret),
        )
    yield
    await clients.get_backend_client().aclose()
    await clients.get_manager_client().aclose()


def render_verdict_response(
    request: Request,
    kind: str,
    *,
    verdict: Verdict | None = None,
    request_id: str = "",
) -> Response:
    """One refusal, two renderings — HTML for people, JSON for code (D7)."""
    config = get_config()
    accept_language = request.headers.get("Accept-Language")
    if not is_navigation(request):
        return JSONResponse(
            error_payload(kind, request_id, accept_language=accept_language),
            status_code=json_status(kind),
        )

    if kind == DECISION_LOGIN:
        return HTMLResponse(render_login_handoff(config.login_path), status_code=PAGE_HTTP_STATUS)

    html = render_page(
        kind,
        app_name=verdict.app_name if verdict else None,
        owner_name=verdict.owner_name if verdict else None,
        square_url=config.square_url,
        request_id=request_id,
        accept_language=accept_language,
    )
    return HTMLResponse(html, status_code=PAGE_HTTP_STATUS)


def _needs_trailing_slash(request: Request, slug: str) -> bool:
    """Is this a browser navigation to the bare app root, without the slash?

    ``/apps/foo`` and ``/apps/foo/`` reach the same page, but they are NOT the
    same base for relative URLs: a document at ``/apps/foo`` resolves
    ``./assets/x.js`` against ``/apps/`` and asks for ``/apps/assets/x.js``,
    which is a different app's slug and 404s. The app is not at fault — the skill
    pack explicitly sanctions relative paths ("要么用 url() 前缀，要么用相对路径")
    and a bundler emitting ``./assets/…`` is the normal way to be prefix-agnostic.
    Serving that document under a slash-less URL is what breaks it, so the fix
    belongs on the platform side rather than in every app's bundler config.

    Only GET/HEAD. Those are the navigations whose relative references matter;
    redirecting an API call would add a hop to a request that never resolves a
    relative URL against anything.
    """
    if request.method not in ("GET", "HEAD"):
        return False
    prefix = entry_prefix_for(slug, get_config().entry_prefix)
    return request.url.path == prefix


async def handle_entry(request: Request) -> Response:
    started = time.monotonic()
    slug = request.path_params.get("slug", "")
    tail = request.path_params.get("tail", "")
    request_id = uuid.uuid4().hex

    if not is_valid_slug(slug):
        # Answered locally: a path that cannot be a slug is not worth an RPC,
        # and refusing to ask also keeps scanners from using the internal
        # endpoint as an existence oracle.
        return render_verdict_response(request, DECISION_NOT_FOUND, request_id=request_id)

    verdict = await authorize(
        slug=slug,
        access_token=extract_access_token(request),
        request_id=request_id,
        client_ip=request.client.host if request.client else None,
    )

    if not verdict.allowed:
        logger.info(
            "app_proxy.request request_id=%s slug=%s decision=%s reason=%s cache_hit=%s latency_ms=%.1f",
            request_id,
            slug,
            verdict.decision,
            verdict.reason,
            verdict.cache_hit,
            (time.monotonic() - started) * 1000,
        )
        return render_verdict_response(request, verdict.decision, verdict=verdict, request_id=request_id)

    if _needs_trailing_slash(request, slug):
        # After authorize(), so the non-allow branches keep their exact behaviour:
        # the login hand-off, 404, stopped and recovering pages are platform HTML
        # that resolves no relative URLs, and redirecting them would buy a hop and
        # a changed return address for nothing. Only the document that is actually
        # the app's own needs its base corrected.
        location = f"{request.url.path}/"
        if request.url.query:
            location = f"{location}?{request.url.query}"
        return RedirectResponse(location, status_code=308)

    # Imported here, not at module scope: the proxy pulls in the upstream
    # transport machinery, and keeping it out of the import graph of the page
    # path means a proxy-side import error cannot take the fallback pages down
    # with it.
    from app_proxy.proxy import forward

    return await forward(request, slug=slug, tail=tail, verdict=verdict, request_id=request_id, started=started)


async def handle_entry_ws(websocket: WebSocket) -> None:
    """Refuse an upgrade with a close code — never with a page.

    WS reverse proxying is Wave 4 (T079/T080). Until it lands, an allowed
    connection is closed with its own code rather than half-proxied, and the
    refusals reuse the same verdict so a revoked user cannot open a socket that
    the HTTP path would have blocked.

    Closed **without** accepting: the handshake never completes, so no
    unauthorised peer is ever briefly connected.
    """
    slug = websocket.path_params.get("slug", "")
    request_id = uuid.uuid4().hex
    if not is_valid_slug(slug):
        await websocket.close(code=ws_close_code(DECISION_NOT_FOUND))
        return

    verdict = await authorize(
        slug=slug,
        access_token=extract_access_token(websocket),
        request_id=request_id,
        client_ip=websocket.client.host if websocket.client else None,
    )
    code = WS_CLOSE_NOT_IMPLEMENTED if verdict.decision == DECISION_ALLOW else ws_close_code(verdict.decision)
    logger.info(
        "app_proxy.request request_id=%s slug=%s protocol=ws decision=%s close_code=%s",
        request_id,
        slug,
        verdict.decision,
        code,
    )
    await websocket.close(code=code)


def create_app() -> FastAPI:
    application = FastAPI(
        title="BiSheng app-proxy",
        description="Hosted-app entry: session check, header strip/inject, fallback pages, reverse proxy",
        version="3.0.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @application.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    prefix = get_config().entry_prefix.rstrip("/")
    # Two routes, because ``{tail:path}`` does not match the empty string:
    # ``/apps/foo`` and ``/apps/foo/x`` are both entry points (AC-25).
    application.add_route(f"{prefix}/{{slug}}", handle_entry, methods=ENTRY_METHODS)
    application.add_route(f"{prefix}/{{slug}}/{{tail:path}}", handle_entry, methods=ENTRY_METHODS)
    # Via ``application.router``, not ``application``: FastAPI dropped its own
    # ``add_websocket_route`` passthrough (gone by 0.141), while the Starlette
    # Router method has been stable across both. Our pin is a floor, not a
    # ceiling, so the entrypoint must not depend on a version-specific alias —
    # tests resolved 0.121 while a fresh ``uv sync`` resolved 0.141 and the
    # module failed to import there.
    application.router.add_websocket_route(f"{prefix}/{{slug}}", handle_entry_ws)
    application.router.add_websocket_route(f"{prefix}/{{slug}}/{{tail:path}}", handle_entry_ws)
    return application


app = create_app()
