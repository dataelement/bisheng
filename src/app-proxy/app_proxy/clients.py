"""The two HMAC-signed RPCs app-proxy is allowed to make, plus their caches.

Deliberately **two** clients with **two** independent caches (D6 / D5.1):

* ``BackendAuthzClient`` — "who is this and may they enter", keyed by
  ``(sha256(session token), slug)``. Follows permission changes.
* ``ManagerRouteClient`` — "where does this app live right now", keyed by
  ``app_id``. Follows releases.

Merging them (or their caches) would make "change visibility" and "switch
version" step on each other: a permission revoke would be masked by a route
cache entry and vice versa. The 30s retirement grace in runtime-manager is
sized against the 3s route TTL, so shortening one without the other reopens the
502 window during a version switch.

Signing string is byte-for-byte runtime-manager's / F014's::

    METHOD + "\\n" + PATH + "\\n" + raw_body

PATH excludes the query string, so a read with ``httpx.params`` does not have
to re-derive the signature.

**Empty secret fails closed.** A rollout that forgot one of the two secrets
would otherwise send unsigned requests, and against a peer misconfigured the
same way it would authorise anonymous traffic into every hosted app.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

import httpx

from app_proxy.config import Config, get_config

logger = logging.getLogger(__name__)

T = TypeVar("T")


class InternalRpcError(RuntimeError):
    """Any failure to get a trustworthy answer out of a peer.

    Every call site treats it as **deny / fail-closed**, never as "carry on"
    (AC-12). It carries ``peer`` so the log line says which hop broke.
    """

    def __init__(self, peer: str, message: str) -> None:
        super().__init__(f"{peer}: {message}")
        self.peer = peer


def compute_signature(method: str, path: str, raw_body: bytes, secret: str) -> str:
    """Canonical HMAC-SHA256 hex digest, shared with runtime-manager."""
    msg = f"{method.upper()}\n{path}\n".encode() + (raw_body or b"")
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def token_fingerprint(token: str | None) -> str:
    """Cache key material for a session token.

    Hashed, never the raw JWT: the cache dict ends up in heap dumps and in the
    occasional debug log line, and the raw value is a live session.
    """
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


@dataclass
class _Entry(Generic[T]):
    value: T
    expires_at: float


class TTLCache(Generic[T]):
    """Tiny monotonic-clock TTL map.

    The clock is injectable because "does the entry really expire after 3s"
    is a behaviour we assert, and asserting it with real sleeps would put three
    seconds of dead time into the suite for every such case.
    """

    def __init__(self, ttl_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self._data: dict[Any, _Entry[T]] = {}

    def get(self, key: Any) -> T | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        if entry.expires_at <= self._clock():
            self._data.pop(key, None)
            return None
        return entry.value

    def set(self, key: Any, value: T) -> None:
        self._data[key] = _Entry(value=value, expires_at=self._clock() + self.ttl_seconds)

    def invalidate(self, key: Any) -> None:
        self._data.pop(key, None)

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:  # pragma: no cover - debugging convenience
        return len(self._data)


class HmacClient:
    """Shared transport: sign, send, translate failures into one exception."""

    peer = "peer"

    def __init__(
        self,
        base_url: str,
        secret: str,
        *,
        signature_header: str = "X-Signature",
        timeout: float = 3.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.secret = secret
        self.signature_header = signature_header
        self.timeout = timeout
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                transport=self._transport,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _send(self, method: str, path: str, *, json: Any | None = None) -> httpx.Response:
        if not self.secret:
            raise InternalRpcError(self.peer, "HMAC secret is not configured (fail-closed)")
        raw = b"" if json is None else httpx.Request("POST", "http://x", json=json).content
        headers = {self.signature_header: compute_signature(method, path, raw, self.secret)}
        if json is not None:
            headers["Content-Type"] = "application/json"
        try:
            return await self._http().request(method, path, content=raw or None, headers=headers)
        except httpx.HTTPError as exc:
            raise InternalRpcError(self.peer, f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _unwrap(payload: Any) -> Any:
        """Accept both the platform envelope and a bare body.

        The backend wraps handler returns in ``{status_code, status_message,
        data}``; runtime-manager answers bare. Rather than pin the internal
        endpoint to one of the two shapes (and break the day someone routes it
        through the standard response helper), unwrap when the envelope is
        recognisable.
        """
        if isinstance(payload, dict) and "data" in payload and "status_code" in payload:
            return payload["data"]
        return payload


class BackendAuthzClient(HmacClient):
    """``POST /api/v1/internal/app-proxy/authorize`` + the authz cache.

    The response deliberately carries **no upstream address** — that is the
    manager's answer, on its own cache clock (D5.1).
    """

    peer = "backend"
    path = "/api/v1/internal/app-proxy/authorize"

    def __init__(self, *args, ttl_seconds: float = 3.0, clock: Callable[[], float] = time.monotonic, **kwargs):
        super().__init__(*args, **kwargs)
        self.cache: TTLCache[dict] = TTLCache(ttl_seconds, clock=clock)

    async def authorize(
        self,
        *,
        slug: str,
        access_token: str | None,
        request_id: str,
        client_ip: str | None = None,
    ) -> dict:
        key = (token_fingerprint(access_token), slug)
        cached = self.cache.get(key)
        if cached is not None:
            return {**cached, "cache_hit": True}

        body = {
            "slug": slug,
            "access_token": access_token,
            "request_id": request_id,
            "client_ip": client_ip,
        }
        response = await self._send("POST", self.path, json=body)
        if response.status_code >= 500:
            raise InternalRpcError(self.peer, f"HTTP {response.status_code}")
        if response.status_code in (401, 403):
            # Our own signature was rejected — a deployment error, not a user
            # verdict. Must not be mistaken for "this visitor is forbidden".
            raise InternalRpcError(self.peer, f"HTTP {response.status_code} (signature rejected?)")
        try:
            payload = self._unwrap(response.json())
        except ValueError as exc:
            raise InternalRpcError(self.peer, f"non-JSON response: {exc}")
        if not isinstance(payload, dict) or "decision" not in payload:
            raise InternalRpcError(self.peer, "response has no decision field")

        self.cache.set(key, payload)
        return {**payload, "cache_hit": False}


class ManagerRouteClient(HmacClient):
    """``GET /v1/apps/{app_id}/route`` + the route cache.

    ``None`` means "the manager knows this app and it has no live instance"
    (404) — an expected answer during stop / crash windows, not an error.
    """

    peer = "manager"

    def __init__(self, *args, ttl_seconds: float = 3.0, clock: Callable[[], float] = time.monotonic, **kwargs):
        super().__init__(*args, **kwargs)
        self.cache: TTLCache[dict] = TTLCache(ttl_seconds, clock=clock)

    async def route(self, app_id: str, *, refresh: bool = False) -> dict | None:
        """Resolve the upstream. ``refresh=True`` bypasses **and** drops the entry.

        That flag is the D5.1 invalidation path: a connection error against a
        cached address means the address is stale (version switch, restart), so
        the entry is dropped and re-fetched exactly once before we give up and
        render "应用恢复中".
        """
        if refresh:
            self.cache.invalidate(app_id)
        else:
            cached = self.cache.get(app_id)
            if cached is not None:
                return {**cached, "cache_hit": True}

        response = await self._send("GET", f"/v1/apps/{app_id}/route")
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise InternalRpcError(self.peer, f"HTTP {response.status_code}")
        try:
            payload = self._unwrap(response.json())
        except ValueError as exc:
            raise InternalRpcError(self.peer, f"non-JSON response: {exc}")
        if not isinstance(payload, dict) or not payload.get("upstream"):
            raise InternalRpcError(self.peer, "response has no upstream field")

        self.cache.set(app_id, payload)
        return {**payload, "cache_hit": False}


_backend_client: BackendAuthzClient | None = None
_manager_client: ManagerRouteClient | None = None


def build_clients(config: Config | None = None) -> tuple[BackendAuthzClient, ManagerRouteClient]:
    config = config or get_config()
    backend = BackendAuthzClient(
        config.backend_base,
        config.backend_secret,
        signature_header=config.signature_header,
        timeout=config.internal_timeout_seconds,
        ttl_seconds=config.authz_ttl_seconds,
    )
    manager = ManagerRouteClient(
        config.manager_base,
        config.manager_secret,
        signature_header=config.signature_header,
        timeout=config.internal_timeout_seconds,
        ttl_seconds=config.route_ttl_seconds,
    )
    return backend, manager


def get_backend_client() -> BackendAuthzClient:
    global _backend_client
    if _backend_client is None:
        _backend_client, _ = build_clients()
    return _backend_client


def get_manager_client() -> ManagerRouteClient:
    global _manager_client
    if _manager_client is None:
        _, _manager_client = build_clients()
    return _manager_client


def set_clients(
    backend: BackendAuthzClient | None = None,
    manager: ManagerRouteClient | None = None,
) -> None:
    """Test / bootstrap seam. Passing ``None`` for both re-reads the config."""
    global _backend_client, _manager_client
    _backend_client = backend
    _manager_client = manager
