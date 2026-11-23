import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any, Protocol

from loguru import logger

STREAM_HEARTBEAT_SECONDS = 10.0
STREAM_RESPONSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
}


class DisconnectAwareRequest(Protocol):
    async def is_disconnected(self) -> bool: ...


async def stream_with_heartbeat(
    request: DisconnectAwareRequest,
    source: AsyncIterator[str],
    heartbeat_seconds: float = STREAM_HEARTBEAT_SECONDS,
    heartbeat_event: str = ": ping\n\n",
) -> AsyncIterator[str]:
    """Forward an SSE stream while keeping idle connections alive.

    Agent tool calls may produce no model chunks for long periods. A small SSE
    comment prevents clients and reverse proxies from treating that period as
    an idle connection. The producer is cancelled as soon as the client
    disconnects so model and tool work does not continue unnecessarily.
    """
    # Keep backpressure from the HTTP response path so a slow client cannot
    # make model chunks accumulate without bound in memory.
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue(maxsize=1)

    async def produce() -> None:
        try:
            async for item in source:
                await queue.put(("data", item))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await queue.put(("error", exc))
        else:
            await queue.put(("end", None))

    producer = asyncio.create_task(produce())
    try:
        while True:
            if await request.is_disconnected():
                logger.info("SSE client disconnected")
                break

            try:
                event_type, payload = await asyncio.wait_for(queue.get(), timeout=heartbeat_seconds)
            except TimeoutError:
                yield heartbeat_event
                continue

            if event_type == "data":
                yield payload
            elif event_type == "error":
                raise payload
            else:
                break
    finally:
        if not producer.done():
            producer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await producer
