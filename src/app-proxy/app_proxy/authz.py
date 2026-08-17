"""Ask the backend "who is this, and may they enter" — and never guess.

app-proxy holds no permission logic (D6-C). The five-step decision (layer
deployed → session → app exists and has been online → visible to this user →
app state) lives once, in the backend, on top of F048. Here we only:

1. pull the session token out of the request the same way the platform
   middleware does (cookie first, then ``Authorization: Bearer``);
2. call the internal endpoint, cached 3s per ``(session, slug)``;
3. turn *anything* that is not a clean verdict into a refusal.

Point 3 is AC-12 and is the reason :data:`KNOWN_DECISIONS` exists: a backend
deployed ahead of this process could answer with a verdict string this build
has never seen, and the one thing that must not happen is for it to fall
through to "forward the request".
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from starlette.requests import HTTPConnection

from app_proxy.clients import InternalRpcError, get_backend_client
from app_proxy.config import ACCESS_TOKEN_COOKIE

logger = logging.getLogger(__name__)

DECISION_ALLOW = "allow"
DECISION_LOGIN = "login"
DECISION_FORBIDDEN = "forbidden"
DECISION_STOPPED = "stopped"
DECISION_NOT_FOUND = "not_found"
DECISION_NOT_ENABLED = "not_enabled"
#: Local-only verdict: we could not get a trustworthy answer. Never sent by the
#: backend as a happy path, but accepted from it too (16146 fail-closed).
DECISION_UNAVAILABLE = "unavailable"

KNOWN_DECISIONS = frozenset(
    {
        DECISION_ALLOW,
        DECISION_LOGIN,
        DECISION_FORBIDDEN,
        DECISION_STOPPED,
        DECISION_NOT_FOUND,
        DECISION_NOT_ENABLED,
        DECISION_UNAVAILABLE,
    }
)

#: A slug is a URL identity (AC-08), so it is validated here rather than being
#: handed to two peers as-is. Rejecting locally also keeps ``/apps/../..`` and
#: scanner traffic from turning the internal endpoint into a load amplifier.
SLUG_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


@dataclass(frozen=True)
class Verdict:
    """The answer, plus the material needed to act on it."""

    decision: str
    material: dict[str, str] = field(default_factory=dict)
    obo_token: str | None = None
    app_id: str | None = None
    app_name: str | None = None
    owner_name: str | None = None
    app_state: str | None = None
    cache_hit: bool = False
    reason: str = ""

    @property
    def allowed(self) -> bool:
        return self.decision == DECISION_ALLOW


def is_valid_slug(slug: str) -> bool:
    return bool(SLUG_PATTERN.match(slug or ""))


def extract_access_token(connection: HTTPConnection) -> str | None:
    """Mirror of ``_extract_http_access_token`` (``bisheng/utils/http_middleware.py``).

    Cookie first — that is what a browser navigating to ``/apps/{slug}`` sends,
    and the whole no-second-login promise (AC-26) rides on it being host-only
    and ``path=/`` (K7). Bearer second, because the platform SPA keeps its token
    in localStorage and an app embedded in it may call through with a header.
    """
    token = connection.cookies.get(ACCESS_TOKEN_COOKIE)
    if token:
        return token
    header = (connection.headers.get("Authorization") or "").strip()
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return None


def _coerce_material(payload: dict[str, Any]) -> dict[str, str]:
    raw = payload.get("headers") or {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if v is not None}


async def authorize(
    *,
    slug: str,
    access_token: str | None,
    request_id: str,
    client_ip: str | None = None,
) -> Verdict:
    """One RPC (or one cache hit) → one :class:`Verdict`, refusal-by-default."""
    try:
        payload = await get_backend_client().authorize(
            slug=slug,
            access_token=access_token,
            request_id=request_id,
            client_ip=client_ip,
        )
    except InternalRpcError as exc:
        # Deliberately not cached: caching an outage would stretch a one-second
        # blip into three seconds of refusals for every visitor.
        logger.warning("app_proxy.authz slug=%s request_id=%s fail_closed=%s", slug, request_id, exc)
        return Verdict(decision=DECISION_UNAVAILABLE, reason=str(exc))

    decision = str(payload.get("decision") or "")
    if decision not in KNOWN_DECISIONS:
        logger.error(
            "app_proxy.authz slug=%s request_id=%s unknown decision %r — refusing",
            slug,
            request_id,
            decision,
        )
        return Verdict(decision=DECISION_UNAVAILABLE, reason=f"unknown decision {decision!r}")

    material = _coerce_material(payload)
    app_id = payload.get("app_id") or material.get("X-BiSheng-App-Id")
    return Verdict(
        decision=decision,
        material=material,
        obo_token=payload.get("obo_token"),
        app_id=str(app_id) if app_id else None,
        app_name=payload.get("app_name"),
        owner_name=payload.get("owner_name"),
        app_state=payload.get("app_state"),
        cache_hit=bool(payload.get("cache_hit")),
    )
