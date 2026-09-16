"""流心跳不打断生产者，期限和取消负责回收同一个生产任务。"""

import asyncio
import time


async def bounded_qa_stream(source, *, timeout, heartbeat, phase_deadline=None):
    deadline = time.monotonic() + timeout
    pending = None
    try:
        while True:
            if pending is None:
                pending = asyncio.create_task(source.__anext__())
            phase_end = phase_deadline() if phase_deadline is not None else None
            remaining = min(deadline, phase_end if phase_end is not None else deadline) - time.monotonic()
            if remaining <= 0:
                raise asyncio.TimeoutError("question deadline exceeded")
            done, _ = await asyncio.wait({pending}, timeout=min(heartbeat, remaining))
            if not done:
                yield ": keep-alive\n\n"
                continue
            try:
                chunk = pending.result()
            except StopAsyncIteration:
                return
            pending = None
            yield chunk
    finally:
        if pending is not None:
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await source.aclose()
