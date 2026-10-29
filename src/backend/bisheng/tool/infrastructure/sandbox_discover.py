"""Replica URL discovery by hostname pattern (F068 T016). No docker / k8s client."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx
from loguru import logger

GetAddrInfo = Callable[..., Any]
HealthProbe = Callable[[str, int], bool]
Clock = Callable[[], float]


def _http_health(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        resp = httpx.get(f"http://{host}:{port}/health", timeout=timeout)
    except httpx.HTTPError:
        return False
    return resp.status_code == 200


class ReplicaDiscoverer:
    """Scan ``pattern`` from ``index_start`` until NXDOMAIN.

    A failed ``/health`` skips that index and continues. Cached entries are
    hostname URLs (``http://code-runner-1:8080``), never the A-record IP.
    Non-empty ``endpoints`` skip DNS entirely.

    ``urls()`` scans only when the cache is empty (first lease). Afterwards it
    returns the last good list. ``discover_ttl_s`` is the background refresh
    interval, not a cache expiry — the lease path never waits on a rescan.
    """

    def __init__(
        self,
        *,
        endpoints: list[str] | None = None,
        discover_host_pattern: str = "code-runner-{n}",
        discover_index_start: int = 1,
        discover_max: int = 32,
        discover_ttl_s: float = 60,
        discover_port: int = 8080,
        getaddrinfo: GetAddrInfo | None = None,
        health_probe: HealthProbe | None = None,
        clock: Clock | None = None,
        background_refresh: bool = False,
    ):
        self.endpoints = [str(url).rstrip("/") for url in (endpoints or [])]
        self.discover_host_pattern = discover_host_pattern
        self.discover_index_start = int(discover_index_start)
        self.discover_max = int(discover_max)
        self.discover_ttl_s = float(discover_ttl_s)
        self.discover_port = int(discover_port)
        self.getaddrinfo = getaddrinfo or socket.getaddrinfo
        self.health_probe = health_probe if health_probe is not None else _http_health
        self.clock = clock or time.monotonic
        self.background_refresh = background_refresh
        self._cached: list[str] | None = None
        self._guard = threading.Lock()
        self._stop = threading.Event()
        self._refresh_thread: threading.Thread | None = None

    @classmethod
    def from_conf(cls, conf, **inject) -> ReplicaDiscoverer:
        return cls(
            endpoints=list(getattr(conf, "endpoints", None) or []),
            discover_host_pattern=getattr(conf, "discover_host_pattern", "code-runner-{n}"),
            discover_index_start=getattr(conf, "discover_index_start", 1),
            discover_max=getattr(conf, "discover_max", 32),
            discover_ttl_s=getattr(conf, "discover_ttl_s", 60),
            discover_port=getattr(conf, "discover_port", 8080),
            **inject,
        )

    def urls(self) -> list[str]:
        if self.endpoints:
            return list(self.endpoints)
        with self._guard:
            if self._cached is not None:
                return list(self._cached)
            found = self._scan()
            self._cached = found
            self._start_refresh_locked()
            return list(found)

    def refresh(self) -> list[str]:
        """Rescan. An empty result keeps the previous list so a blip cannot wipe the pool."""
        if self.endpoints:
            return list(self.endpoints)
        found = self._scan()
        with self._guard:
            if found or self._cached is None:
                self._cached = found
            return list(self._cached or [])

    def close(self) -> None:
        self._stop.set()

    def _start_refresh_locked(self) -> None:
        if not self.background_refresh or self._refresh_thread is not None:
            return
        if self.discover_ttl_s <= 0:
            return
        thread = threading.Thread(
            target=self._refresh_loop,
            name="sandbox-replica-discover",
            daemon=True,
        )
        self._refresh_thread = thread
        thread.start()

    def _refresh_loop(self) -> None:
        while not self._stop.wait(self.discover_ttl_s):
            try:
                self.refresh()
            except Exception:
                logger.exception("sandbox replica refresh failed; keeping last list")

    def _scan(self) -> list[str]:
        found: list[str] = []
        start = self.discover_index_start
        for offset in range(self.discover_max):
            n = start + offset
            host = self.discover_host_pattern.replace("{n}", str(n))
            if not self._dns_ok(host):
                break
            if not self.health_probe(host, self.discover_port):
                continue
            found.append(f"http://{host}:{self.discover_port}")
        return found

    def _dns_ok(self, host: str) -> bool:
        try:
            self.getaddrinfo(host, self.discover_port)
        except OSError:
            return False
        return True


_SHARED_GUARD = threading.Lock()
_SHARED: dict[tuple, ReplicaDiscoverer] = {}


def _shared_key(
    *,
    discover_host_pattern: str,
    discover_index_start: int,
    discover_max: int,
    discover_ttl_s: float,
    discover_port: int,
) -> tuple:
    return (
        discover_host_pattern,
        int(discover_index_start),
        int(discover_max),
        float(discover_ttl_s),
        int(discover_port),
    )


def shared_discoverer(
    *,
    discover_host_pattern: str = "code-runner-{n}",
    discover_index_start: int = 1,
    discover_max: int = 32,
    discover_ttl_s: float = 60,
    discover_port: int = 8080,
) -> ReplicaDiscoverer:
    """Process-wide discoverer. Lease path shares one list; TTL is the refresh interval."""
    key = _shared_key(
        discover_host_pattern=discover_host_pattern,
        discover_index_start=discover_index_start,
        discover_max=discover_max,
        discover_ttl_s=discover_ttl_s,
        discover_port=discover_port,
    )
    with _SHARED_GUARD:
        disc = _SHARED.get(key)
        if disc is None:
            disc = ReplicaDiscoverer(
                endpoints=[],
                discover_host_pattern=discover_host_pattern,
                discover_index_start=discover_index_start,
                discover_max=discover_max,
                discover_ttl_s=discover_ttl_s,
                discover_port=discover_port,
                background_refresh=True,
            )
            _SHARED[key] = disc
        return disc


def clear_shared_discoverers() -> None:
    with _SHARED_GUARD:
        discs = list(_SHARED.values())
        _SHARED.clear()
    for disc in discs:
        disc.close()


def discover(
    conf=None,
    *,
    endpoints: list[str] | None = None,
    discover_host_pattern: str = "code-runner-{n}",
    discover_index_start: int = 1,
    discover_max: int = 32,
    discover_ttl_s: float = 60,
    discover_port: int = 8080,
    getaddrinfo: GetAddrInfo | None = None,
    health_probe: HealthProbe | None = None,
    clock: Clock | None = None,
    discoverer: ReplicaDiscoverer | None = None,
) -> list[str]:
    """Resolve replica URLs. ``endpoints`` non-empty skips DNS (decision 12)."""
    if discoverer is not None:
        return discoverer.urls()
    if conf is not None:
        return ReplicaDiscoverer.from_conf(
            conf,
            getaddrinfo=getaddrinfo,
            health_probe=health_probe,
            clock=clock,
        ).urls()
    return ReplicaDiscoverer(
        endpoints=endpoints,
        discover_host_pattern=discover_host_pattern,
        discover_index_start=discover_index_start,
        discover_max=discover_max,
        discover_ttl_s=discover_ttl_s,
        discover_port=discover_port,
        getaddrinfo=getaddrinfo,
        health_probe=health_probe,
        clock=clock,
    ).urls()
