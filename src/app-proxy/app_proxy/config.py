"""Process configuration — environment variables only, never the platform config.yaml.

app-proxy does not import ``bisheng`` (D5-C), so it cannot read
``settings.app_runtime``. The deployment is responsible for keeping the two
sides in sync; the mapping below is the contract (design §4.2 ⑧ / K10):

============================== ==============================================
env var                        backend-side counterpart
============================== ==============================================
``APP_PROXY_BACKEND_BASE``     the platform API base (``127.0.0.1:7860``)
``APP_PROXY_MANAGER_BASE``     ``settings.app_runtime.manager_base_url``
``APP_PROXY_BACKEND_SECRET``   ``settings.app_runtime.proxy_hmac_secret``
``APP_PROXY_MANAGER_SECRET``   ``settings.app_runtime.manager_hmac_secret``
``APP_PROXY_ENTRY_BASE_URL``   ``settings.app_runtime.entry_base_url``
============================== ==============================================

Both secrets fail **closed**: an empty secret makes every RPC raise before it
leaves the process rather than silently sending unsigned requests that the
peers would reject anyway (and, on a peer misconfigured the same way, accept).

The two TTLs are separate knobs even though both default to 3 seconds — the
authz cache follows permission changes, the route cache follows releases (D5.1).
Collapsing them would make "change visibility" and "switch version" interfere.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8090

#: URL prefix this proxy owns. ``/apps/{slug}`` is a product-visible contract
#: (AC-25) — it appears in QR codes and bookmarks, so it is not configurable
#: per deployment; the variable exists only so tests can mount elsewhere.
DEFAULT_ENTRY_PREFIX = "/apps"

#: Platform session cookie. Must match ``_extract_http_access_token``
#: (``bisheng/utils/http_middleware.py:60-73``). The cookie is host-only and
#: ``path=/``, which is exactly why ``/apps/*`` on the same origin gets it for
#: free — the whole "no second login" promise (AC-26) rests on this (K7).
ACCESS_TOKEN_COOKIE = "access_token_cookie"

#: Where the login handoff page sends the browser. ``/admin`` is platform's
#: SPA; unauthenticated it renders ``LoginPage``, and with SSO configured it
#: bounces to the IdP itself (D7).
DEFAULT_LOGIN_PATH = "/admin"

#: "返回广场" target on the fallback pages. The square is F056's page and its
#: final route is not fixed yet, so this stays an env knob; the default points
#: at the end-user SPA root.
DEFAULT_SQUARE_URL = "/workspace"

#: Variables a deployment must set explicitly. Every default below is a
#: single-host loopback convenience, so a deployment that leaves any of these
#: unset is talking to itself: ``backend_base`` / ``manager_base`` point at
#: ``127.0.0.1`` (in a container, that is the container), and both secrets
#: default to empty, which is **fail closed** — the process still starts, still
#: reports healthy, and renders the fallback page on every single request.
#: ``docker/verify-app-runtime-compose.sh`` asserts the compose file sets them.
REQUIRED_ENV: tuple[str, ...] = (
    "APP_PROXY_HOST",
    "APP_PROXY_PORT",
    "APP_PROXY_BACKEND_BASE",
    "APP_PROXY_MANAGER_BASE",
    "APP_PROXY_BACKEND_SECRET",
    "APP_PROXY_MANAGER_SECRET",
)

#: app-proxy keeps no state on disk, so being containerised adds nothing.
CONTAINERISED_REQUIRED_ENV: tuple[str, ...] = ()


def _env_str(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return default if value is None else value.strip()


def _env_float(name: str, default: float) -> float:
    raw = _env_str(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env_str(name).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    """Immutable process configuration.

    Frozen for the same reason as runtime-manager's: tests swap the whole
    object through :func:`set_config` instead of mutating shared state.
    """

    # --- transport --------------------------------------------------------
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    entry_prefix: str = DEFAULT_ENTRY_PREFIX

    # --- peers ------------------------------------------------------------
    backend_base: str = "http://127.0.0.1:7860"
    manager_base: str = "http://127.0.0.1:8091"
    backend_secret: str = ""
    manager_secret: str = ""
    signature_header: str = "X-Signature"

    # --- caches (D6 / D5.1; two independent knobs on purpose) -------------
    authz_ttl_seconds: float = 3.0
    route_ttl_seconds: float = 3.0

    # --- timeouts ---------------------------------------------------------
    #: Internal RPCs are on loopback; a slow one must fail fast and closed.
    internal_timeout_seconds: float = 3.0
    #: Upstream connect must fail fast (that is what triggers the route-cache
    #: invalidation retry, D5.1); reads must not, because hosted apps stream.
    upstream_connect_timeout_seconds: float = 3.0
    upstream_read_timeout_seconds: float = 600.0

    # --- pages ------------------------------------------------------------
    login_path: str = DEFAULT_LOGIN_PATH
    square_url: str = DEFAULT_SQUARE_URL
    #: Absolute externally reachable base (``https://host:4101``). Only used to
    #: fill ``X-Forwarded-Proto`` / ``X-Forwarded-Host`` when the request
    #: carries nothing trustworthy; normally nginx-facing values win.
    entry_base_url: str = ""

    # --- staged capability ------------------------------------------------
    #: WebSocket reverse proxying is Wave 4 (T079/T080). Until then an upgrade
    #: request is refused with a close code rather than half-proxied.
    ws_proxy_enabled: bool = False

    def with_overrides(self, **kwargs) -> Config:
        return replace(self, **kwargs)


def load_config() -> Config:
    """Build a :class:`Config` from the ``APP_PROXY_*`` environment variables."""
    return Config(
        host=_env_str("APP_PROXY_HOST", DEFAULT_HOST) or DEFAULT_HOST,
        port=int(_env_str("APP_PROXY_PORT", str(DEFAULT_PORT)) or DEFAULT_PORT),
        entry_prefix=_env_str("APP_PROXY_ENTRY_PREFIX", DEFAULT_ENTRY_PREFIX) or DEFAULT_ENTRY_PREFIX,
        backend_base=_env_str("APP_PROXY_BACKEND_BASE", "http://127.0.0.1:7860") or "http://127.0.0.1:7860",
        manager_base=_env_str("APP_PROXY_MANAGER_BASE", "http://127.0.0.1:8091") or "http://127.0.0.1:8091",
        backend_secret=_env_str("APP_PROXY_BACKEND_SECRET"),
        manager_secret=_env_str("APP_PROXY_MANAGER_SECRET"),
        signature_header=_env_str("APP_PROXY_SIGNATURE_HEADER", "X-Signature") or "X-Signature",
        authz_ttl_seconds=_env_float("APP_PROXY_AUTHZ_TTL_SECONDS", 3.0),
        route_ttl_seconds=_env_float("APP_PROXY_ROUTE_TTL_SECONDS", 3.0),
        internal_timeout_seconds=_env_float("APP_PROXY_INTERNAL_TIMEOUT_SECONDS", 3.0),
        upstream_connect_timeout_seconds=_env_float("APP_PROXY_UPSTREAM_CONNECT_TIMEOUT_SECONDS", 3.0),
        upstream_read_timeout_seconds=_env_float("APP_PROXY_UPSTREAM_READ_TIMEOUT_SECONDS", 600.0),
        login_path=_env_str("APP_PROXY_LOGIN_PATH", DEFAULT_LOGIN_PATH) or DEFAULT_LOGIN_PATH,
        square_url=_env_str("APP_PROXY_SQUARE_URL", DEFAULT_SQUARE_URL) or DEFAULT_SQUARE_URL,
        entry_base_url=_env_str("APP_PROXY_ENTRY_BASE_URL"),
        ws_proxy_enabled=_env_bool("APP_PROXY_WS_PROXY_ENABLED", False),
    )


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def set_config(config: Config | None) -> None:
    """Test / bootstrap seam. Passing ``None`` re-reads the environment."""
    global _config
    _config = config
