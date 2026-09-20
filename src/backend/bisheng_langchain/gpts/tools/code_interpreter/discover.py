"""Replica URL discovery by hostname pattern (F068 T016). No docker / k8s client."""

from __future__ import annotations

import socket
import time
from collections.abc import Callable
from typing import Any

import httpx

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
    """Scan ``pattern`` from ``index_start`` until NXDOMAIN or a probe miss.

    Cached entries are hostname URLs (``http://code-runner-1:8080``), never the
    A-record IP. Non-empty ``endpoints`` skip DNS entirely.
    """

    def __init__(
        self,
        *,
        endpoints: list[str] | None = None,
        discover_host_pattern: str = "code-runner-{n}",
        discover_index_start: int = 1,
        discover_max: int = 32,
        discover_ttl_s: float = 15,
        discover_port: int = 8080,
        getaddrinfo: GetAddrInfo | None = None,
        health_probe: HealthProbe | None = None,
        clock: Clock | None = None,
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
        self._cached: list[str] | None = None
        self._cached_until = 0.0

    @classmethod
    def from_conf(cls, conf, **inject) -> ReplicaDiscoverer:
        return cls(
            endpoints=list(getattr(conf, "endpoints", None) or []),
            discover_host_pattern=getattr(conf, "discover_host_pattern", "code-runner-{n}"),
            discover_index_start=getattr(conf, "discover_index_start", 1),
            discover_max=getattr(conf, "discover_max", 32),
            discover_ttl_s=getattr(conf, "discover_ttl_s", 15),
            discover_port=getattr(conf, "discover_port", 8080),
            **inject,
        )

    def urls(self) -> list[str]:
        if self.endpoints:
            return list(self.endpoints)
        now = self.clock()
        if self._cached is not None and now < self._cached_until:
            return list(self._cached)
        found = self._scan()
        self._cached = found
        self._cached_until = now + self.discover_ttl_s
        return list(found)

    def _scan(self) -> list[str]:
        found: list[str] = []
        start = self.discover_index_start
        for offset in range(self.discover_max):
            n = start + offset
            host = self.discover_host_pattern.replace("{n}", str(n))
            if not self._dns_ok(host):
                break
            if not self.health_probe(host, self.discover_port):
                break
            found.append(f"http://{host}:{self.discover_port}")
        return found

    def _dns_ok(self, host: str) -> bool:
        try:
            self.getaddrinfo(host, self.discover_port)
        except OSError:
            return False
        return True


def discover(
    conf=None,
    *,
    endpoints: list[str] | None = None,
    discover_host_pattern: str = "code-runner-{n}",
    discover_index_start: int = 1,
    discover_max: int = 32,
    discover_ttl_s: float = 15,
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
