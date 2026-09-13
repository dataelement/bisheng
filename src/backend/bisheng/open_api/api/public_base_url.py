"""Browser-facing base URL of this deployment, for URLs handed to external clients.

The backend only needs its own absolute address when it writes that address into
something that leaves the browser: the downloadable skill pack (whose scripts
call the platform from the user's machine) and the install prompt. Behind the
shipped nginx or the commercial gateway the backend sees nothing but the last
proxy hop, so ``request.base_url`` names the internal upstream over plain http.

Resolution order:

1. ``settings.open_api.public_base_url`` — operator-declared, validated at boot;
   the only answer for gateway or path-prefix deployments.
2. ``X-Forwarded-Proto`` / ``X-Forwarded-Host`` set by the reverse proxy (the
   first value of a comma-separated chain), falling back to the ``Host`` header.
   Hosts are whitelisted because the value is written verbatim into generated
   files; ``X-Forwarded-Port`` is ignored on purpose (gateways report their own
   container port there).
3. The socket the server bound to.

Trust note: any client can send these headers, but the derived URL only appears
in that client's own response — the pack is built per request and served with
``Cache-Control: no-store`` — so a spoofed value never reaches anyone else.
"""

from __future__ import annotations

import re

from starlette.requests import Request

from bisheng.common.services.config_service import settings

_HOST_RE = re.compile(
    r"^(?:"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*\.?"
    r"|\[[0-9A-Fa-f:.]+\]"
    r")(?::\d{1,5})?$"
)
_SCHEMES = frozenset({"http", "https"})


def _first(value: str | None) -> str:
    return (value or "").split(",", 1)[0].strip()


def _is_valid_host(value: str) -> bool:
    return bool(value) and _HOST_RE.fullmatch(value) is not None


def _bound_socket(request: Request) -> str:
    server = request.scope.get("server") or ("127.0.0.1", None)
    host, port = server[0], server[1]
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{host}:{port}" if port else host


def resolve_public_base_url(request: Request) -> str:
    """Return ``scheme://host[:port][/root_path]`` without a trailing slash."""
    configured = (settings.open_api.public_base_url or "").strip().rstrip("/")
    if configured:
        return configured

    scheme = _first(request.headers.get("x-forwarded-proto")).lower()
    if scheme not in _SCHEMES:
        scheme = request.url.scheme if request.url.scheme in _SCHEMES else "http"

    host = _first(request.headers.get("x-forwarded-host"))
    if not _is_valid_host(host):
        host = (request.headers.get("host") or "").strip()
    if not _is_valid_host(host):
        host = _bound_socket(request)

    root_path = (request.scope.get("root_path") or "").rstrip("/")
    return f"{scheme}://{host}{root_path}"
