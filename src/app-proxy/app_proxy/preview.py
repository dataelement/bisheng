"""``/apps/preview/{session}`` — the approval-time preview entry (F054 T090, F055 AC-26).

The **same** proxy as ``/apps/{slug}``, pointed at a different question. What
differs is exactly two things, and everything else is reused rather than
re-implemented:

* the verdict comes from ``…/authorize-preview`` instead of ``…/authorize``,
  because "is this the approver this trial was raised for" is a different
  question from "is this app visible to this visitor";
* the upstream is resolved by preview session rather than by app id, because a
  preview has no desired-state record in the manager (F055 keeps it off the
  instance quota that way).

**Header stripping and identity injection are literally the same code** — the
same :func:`app_proxy.proxy.forward`, which calls the same
:func:`app_proxy.headers.build_upstream_headers`. That is a requirement, not a
convenience: a second copy of the strip rule is a second place for
``X_BiSheng_User_Id`` to walk past it (AC-32). The trick that makes it work is
that the "slug" handed to ``forward`` is ``preview/{session}``, so
``entry_prefix_for`` yields ``/apps/preview/{session}`` and both the prefix
strip and ``X-Forwarded-Prefix`` come out right with no branch at all.

**The lifecycle is not controlled here.** app-proxy never starts or reclaims a
preview; F055 does (AC-26 / AC-28). When the upstream is not there — reclaimed,
timed out, or never up — the answer is the ordinary transitional page, exactly
as for an application between containers.
"""

from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from app_proxy.authz import DECISION_NOT_FOUND, authorize_preview, extract_access_token
from app_proxy.config import get_config
from app_proxy.observability import log_request
from app_proxy.routing import entry_prefix_for

logger = logging.getLogger(__name__)

#: Path segment that turns ``/apps/{slug}`` into the preview entry. Must never
#: be a legal application slug — the backend reserves it (``RESERVED_SLUGS`` in
#: ``app_provision_service``), because a route registered ahead of ``{slug}``
#: would otherwise shadow an application permanently.
PREVIEW_SEGMENT = "preview"

#: Same shape the platform mints (a uuid4 hex) and the manager accepts. Checked
#: locally so a path that cannot be a session never becomes an RPC, and so that
#: ``/apps/preview/../..`` dies here.
SESSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$")


def is_valid_session(session: str) -> bool:
    return bool(SESSION_PATTERN.match(session or ""))


def preview_slug(session: str) -> str:
    """The pseudo-slug ``forward`` is given: ``preview/{session}``.

    Not a hack — it is the one value for which ``entry_prefix_for`` produces the
    real entry prefix of this request, which is what both the path strip and
    ``X-Forwarded-Prefix`` are derived from. Passing the bare session instead
    would strip ``/apps/{session}`` and forward ``/preview/…`` to the app.
    """
    return f"{PREVIEW_SEGMENT}/{session}"


def _needs_trailing_slash(request: Request, session: str) -> bool:
    """Is this a browser navigation to the bare preview root, without the slash?"""
    if request.method not in ("GET", "HEAD"):
        return False
    return request.url.path == entry_prefix_for(preview_slug(session), get_config().entry_prefix)


async def handle_preview_entry(request: Request) -> Response:
    """Verdict → forward. Same order, same refusal rendering as the app entry."""
    # Imported here rather than at module scope for the same reason ``main``
    # imports ``forward`` lazily: a proxy-side import error must not take the
    # refusal pages down with it.
    from app_proxy.main import render_verdict_response

    started = time.monotonic()
    session = request.path_params.get("session", "")
    tail = request.path_params.get("tail", "")
    request_id = uuid.uuid4().hex

    if not is_valid_session(session):
        log_request(
            logger,
            request_id=request_id,
            slug=preview_slug(session),
            user_id=None,
            decision=DECISION_NOT_FOUND,
            reason="invalid_preview_session",
            cache_hit=False,
            upstream_status=None,
            latency_ms=(time.monotonic() - started) * 1000,
        )
        return render_verdict_response(request, DECISION_NOT_FOUND, request_id=request_id)

    verdict = await authorize_preview(
        session=session,
        access_token=extract_access_token(request),
        request_id=request_id,
        client_ip=request.client.host if request.client else None,
    )

    if not verdict.allowed:
        log_request(
            logger,
            request_id=request_id,
            slug=preview_slug(session),
            user_id=verdict.visitor_id,
            decision=verdict.decision,
            reason=verdict.reason,
            cache_hit=verdict.cache_hit,
            upstream_status=None,
            latency_ms=(time.monotonic() - started) * 1000,
        )
        return render_verdict_response(request, verdict.decision, verdict=verdict, request_id=request_id)

    if _needs_trailing_slash(request, session):
        # Same reason as the application entry: a document served at
        # ``/apps/preview/{s}`` resolves ``./assets/x.js`` against
        # ``/apps/preview/`` and asks for a different session's asset. After
        # the verdict, so a refusal keeps its exact behaviour.
        location = f"{request.url.path}/"
        if request.url.query:
            location = f"{location}?{request.url.query}"
        log_request(
            logger,
            request_id=request_id,
            slug=preview_slug(session),
            user_id=verdict.visitor_id,
            decision=verdict.decision,
            reason="trailing_slash_redirect",
            cache_hit=verdict.cache_hit,
            upstream_status=None,
            latency_ms=(time.monotonic() - started) * 1000,
        )
        return RedirectResponse(location, status_code=308)

    from app_proxy.proxy import forward

    return await forward(
        request,
        slug=preview_slug(session),
        tail=tail,
        verdict=verdict,
        request_id=request_id,
        started=started,
    )
