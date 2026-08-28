"""In-process concurrency gate that keeps OpenFGA from being overrun.

OpenFGA falls over on too many *simultaneous* requests rather than on too many
per second: a single permission decision fans out into a burst of datastore
queries, so its connection pool drains long before any request-rate figure
looks alarming. A QPS limit stops bounding real usage the moment latency
climbs; a cap on in-flight requests keeps bounding it.

The gate lives in the process, not in Redis. The cluster-wide ceiling is
therefore ``max_in_flight`` times the number of API and Celery processes, and
occupancy is per process too — one worker can be shedding load while another
still has room. That imprecision is the price of keeping a Redis round trip off
the permission hot path.
"""

from __future__ import annotations

import asyncio
import logging
import weakref
from collections.abc import AsyncIterator, MutableMapping
from contextlib import asynccontextmanager

from .exceptions import FGAOverloadError

logger = logging.getLogger(__name__)

DEFAULT_ENABLED = True
DEFAULT_MAX_IN_FLIGHT = 512
DEFAULT_REJECT_RATIO = 0.9
DEFAULT_ACQUIRE_TIMEOUT = 20.0

MIN_REJECT_RATIO = 0.05
MAX_REJECT_RATIO = 1.0
MIN_ACQUIRE_TIMEOUT = 0.1


class OpenFgaConcurrencyGate:
    """Caps concurrent outbound OpenFGA requests and reports how full it is."""

    def __init__(self) -> None:
        self._enabled = DEFAULT_ENABLED
        self._capacity = DEFAULT_MAX_IN_FLIGHT
        self._reject_ratio = DEFAULT_REJECT_RATIO
        self._acquire_timeout = DEFAULT_ACQUIRE_TIMEOUT
        self._in_flight = 0
        # Keyed by event loop: an asyncio.Semaphore binds to the first loop that
        # awaits it, and Celery tasks that spin up their own loop would then hit
        # "bound to a different event loop". Keying by loop also gives capacity
        # changes a natural place to take effect.
        self._semaphores: MutableMapping[
            asyncio.AbstractEventLoop, tuple[asyncio.Semaphore, int]
        ] = weakref.WeakKeyDictionary()

    # ── Settings ─────────────────────────────────────────────────

    def configure(
        self,
        *,
        enabled: bool,
        max_in_flight: int,
        reject_ratio: float,
        acquire_timeout: float,
    ) -> None:
        """Apply admin-editable settings. Cheap enough to call per request."""
        capacity = max(1, int(max_in_flight))
        self._enabled = bool(enabled)
        self._reject_ratio = min(max(float(reject_ratio), MIN_REJECT_RATIO), MAX_REJECT_RATIO)
        self._acquire_timeout = max(MIN_ACQUIRE_TIMEOUT, float(acquire_timeout))
        if capacity != self._capacity:
            logger.info('OpenFGA gate capacity %s -> %s', self._capacity, capacity)
            self._capacity = capacity

    # ── Introspection ────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def in_flight(self) -> int:
        return self._in_flight

    @property
    def occupancy(self) -> float:
        """Fraction of the gate currently held, 0.0 when it is idle."""
        if self._capacity <= 0:
            return 1.0
        return self._in_flight / self._capacity

    @property
    def reject_percent(self) -> int:
        """The configured shed threshold as a whole percent, for user-facing text."""
        return round(self._reject_ratio * 100)

    def is_overloaded(self) -> bool:
        """Whether new work should be turned away instead of queued."""
        return self._enabled and self.occupancy >= self._reject_ratio

    # ── Admission ────────────────────────────────────────────────

    def _semaphore(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        entry = self._semaphores.get(loop)
        if entry is None or entry[1] != self._capacity:
            # A capacity change swaps the semaphore rather than resizing it.
            # Callers already parked on the old one drain against it, so the
            # swap can briefly admit more than the new limit; the overshoot is
            # bounded by what was already in flight and clears within one
            # request cycle. Capacity changes come from an admin config edit,
            # so that window is rare and not worth extra bookkeeping.
            entry = (asyncio.Semaphore(self._capacity), self._capacity)
            self._semaphores[loop] = entry
        return entry[0]

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        """Hold one gate slot for the duration of an outbound OpenFGA request."""
        if not self._enabled:
            yield
            return

        semaphore = self._semaphore()
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=self._acquire_timeout)
        except asyncio.TimeoutError as exc:
            raise FGAOverloadError(
                f'OpenFGA concurrency gate full: {self._in_flight}/{self._capacity} in flight, '
                f'waited {self._acquire_timeout}s'
            ) from exc

        self._in_flight += 1
        try:
            yield
        finally:
            self._in_flight -= 1
            semaphore.release()


openfga_gate = OpenFgaConcurrencyGate()
