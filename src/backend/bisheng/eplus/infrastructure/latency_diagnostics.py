"""Low-volume process-local diagnostics for delayed WebSocket reads."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Awaitable, Callable

from loguru import logger


class EPlusLoopLagMonitor:
    """Measure scheduling lag, not network latency or client display latency."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._clock = clock
        self._sleep = sleep
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is not None:
            return
        started = self._clock()
        self._log("event_loop.started", mono_ms=round(started * 1000, 1))
        self._task = asyncio.create_task(self._run(started), name="eplus-loop-lag")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            # Telemetry failure must not prevent connection/runtime cleanup.
            logger.exception("E+ event loop diagnostics failed")
        self._log("event_loop.stopped", mono_ms=round(self._clock() * 1000, 1))

    async def _run(self, started: float) -> None:
        previous = summary_started = started
        max_lag_ms = 0.0
        samples = 0
        while True:
            # Measure from the previous observation, including delayed first scheduling.
            await self._sleep(max(0.0, previous + 1.0 - self._clock()))
            now = self._clock()
            lag_ms = max(0.0, now - previous - 1.0) * 1000
            max_lag_ms = max(max_lag_ms, lag_ms)
            samples += 1
            if lag_ms >= 1000:
                self._log(
                    "event_loop.lag",
                    warning=True,
                    lag_ms=round(lag_ms, 1),
                    window_start_mono_ms=round(previous * 1000, 1),
                    window_end_mono_ms=round(now * 1000, 1),
                )
            if now - summary_started >= 60:
                self._log(
                    "event_loop.summary",
                    max_lag_ms=round(max_lag_ms, 1),
                    samples=samples,
                    window_start_mono_ms=round(summary_started * 1000, 1),
                    window_end_mono_ms=round(now * 1000, 1),
                )
                summary_started, max_lag_ms, samples = now, 0.0, 0
            previous = now

    @staticmethod
    def _log(event: str, *, warning: bool = False, **fields: float | int) -> None:
        fields = {"pid": os.getpid(), "server_unix_ms": int(time.time() * 1000), **fields}
        bound = logger.bind(eplus_event=event, **fields)
        bound.log("WARNING" if warning else "INFO", "E+ latency event={} fields={}", event, fields)
