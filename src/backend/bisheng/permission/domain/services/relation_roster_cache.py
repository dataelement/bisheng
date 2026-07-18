"""RelationRosterCache — F040 (E): process-local, version-keyed cache for the
ReBAC "roster" that every read request otherwise rebuilds from scratch.

Each ReBAC read (notably knowledge-space ``/children`` deep-expansion, and channel
detail) re-reads + ``json.loads`` + legacy-scans the full relation-binding / model
config and re-derives subject strings. The config is platform-global and changes only
on (rare) admin edits, so caching the *parsed* result keyed by the config row's
``update_time`` lets N consecutive reads reuse one parse — and the key changes the
instant an admin edits the config (``update_time`` has ``onupdate=CURRENT_TIMESTAMP``),
so a stale roster can never be served.

This is the "read-side version-derived key" path F036 design §8 sanctioned — it has
ZERO coupling to the authorization / department / org-sync write paths (no explicit
invalidation hook). It is NOT the cross-request permission cache F036 rejected.

Fail-safe: when the version is unavailable (``None``), every call rebuilds and nothing
is cached — the cache can only ever make reads faster, never serve a wrong roster.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Awaitable, Callable, Hashable
from typing import Any

_MISS = object()
_MAXSIZE = 512


class _VersionedLRU:
    """Per-key LRU storing exactly one ``(version, value)`` per key (we only ever
    need the latest version of a given key). A version mismatch is a miss."""

    def __init__(self, maxsize: int = _MAXSIZE):
        self._data: OrderedDict[Hashable, tuple[Any, Any]] = OrderedDict()
        self._max = maxsize

    def get(self, key: Hashable, version: Any) -> Any:
        entry = self._data.get(key)
        if entry is not None and entry[0] == version:
            self._data.move_to_end(key)
            return entry[1]
        return _MISS

    def set(self, key: Hashable, version: Any, value: Any) -> None:
        self._data[key] = (version, value)
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()


# One bucket per roster kind. Keyed by tenant_id (defensive: config is currently
# global, but keying by tenant keeps it correct if it ever becomes tenant-scoped and
# guarantees no cross-tenant reuse — AC-25).
_BUCKETS: dict[str, _VersionedLRU] = {}


def _bucket(name: str) -> _VersionedLRU:
    return _BUCKETS.setdefault(name, _VersionedLRU())


async def get_or_build(
    *,
    name: str,
    tenant_id: int,
    version: Any | None,
    build: Callable[[], Awaitable[Any]],
) -> Any:
    """Return the cached roster for ``(name, tenant_id, version)`` or build + cache it.

    ``version is None`` (version unavailable) → always rebuild, never cache (fail-safe).
    A cached value of ``[]`` / ``{}`` / ``None`` is a valid hit (sentinel-based).
    """
    if version is None:
        return await build()
    bucket = _bucket(name)
    cached = bucket.get(tenant_id, version)
    if cached is not _MISS:
        return cached
    value = await build()
    bucket.set(tenant_id, version, value)
    return value


def clear_all() -> None:
    """Test/maintenance hook: drop every cached roster."""
    for bucket in _BUCKETS.values():
        bucket.clear()
