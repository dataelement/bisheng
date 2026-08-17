"""Where does this app live right now, and what path does it expect? (D5.1 / D5.2)

Two small, testable pieces sit between the verdict and the forward:

**Address.** The only source of truth for a live instance is runtime-manager's
route table. Not the container name (app-proxy runs as a host systemd unit on
114 and is not on the docker network at all — 坑 30), and not a published host
port (AC-33 forbids one). The manager answers with the container's address on
the ``bisheng-apps`` bridge, which is host-reachable and externally
unreachable, and means the same thing in both deployment shapes.

**Path.** ``/apps/{slug}`` is a platform URL layout, not something a hosted app
should have to know: the same source runs at the root under ``bisheng dev``.
So the prefix comes off here and goes back on as ``X-Forwarded-Prefix`` for the
framework to rebuild absolute URLs from (D5.2).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app_proxy.clients import InternalRpcError, get_manager_client

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Upstream:
    base_url: str
    version_id: str | None = None
    generation: int | None = None
    cache_hit: bool = False


async def resolve_upstream(app_id: str, *, refresh: bool = False) -> Upstream | None:
    """``None`` = nothing to forward to right now → the "恢复中" page, not an error.

    A stopped app, a crash window and the seconds between two containers all
    look the same from here, and all three are legitimately transient.
    """
    try:
        payload = await get_manager_client().route(app_id, refresh=refresh)
    except InternalRpcError as exc:
        logger.warning("app_proxy.route app_id=%s unavailable: %s", app_id, exc)
        return None
    if not payload:
        return None
    return Upstream(
        base_url=str(payload["upstream"]).rstrip("/"),
        version_id=payload.get("version_id"),
        generation=payload.get("generation"),
        cache_hit=bool(payload.get("cache_hit")),
    )


def entry_prefix_for(slug: str, entry_prefix: str = "/apps") -> str:
    return f"{entry_prefix.rstrip('/')}/{slug}"


def strip_entry_prefix(request_path: str, slug: str, entry_prefix: str = "/apps") -> str:
    """``/apps/foo`` → ``/``; ``/apps/foo/`` → ``/``; ``/apps/foo/x`` → ``/x``.

    Both bare forms collapse to ``/`` because an app's index route is ``/`` and
    nothing else; forwarding ``""`` produces a malformed request line and
    forwarding ``/apps/foo`` makes the app 404 its own home page.
    """
    prefix = entry_prefix_for(slug, entry_prefix)
    if request_path == prefix:
        return "/"
    if request_path.startswith(prefix + "/"):
        remainder = request_path[len(prefix) :]
        return remainder or "/"
    # Not ours to strip — forward as-is rather than silently mangling.
    return request_path or "/"
