"""Audit I/O cannot exhaust the executor used by model admission and billing."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from threading import BoundedSemaphore

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="dsh-audit")
_slots = BoundedSemaphore(12)


async def run_audit_blocking(function, *args):
    if not _slots.acquire(blocking=False):
        raise RuntimeError("Audit I/O capacity exhausted")
    try:
        future = _executor.submit(copy_context().run, function, *args)
    except RuntimeError:
        _slots.release()
        raise
    # A cancelled waiter does not free the capacity of a still-running DB/object call.
    future.add_done_callback(lambda _future: _slots.release())
    return await asyncio.wrap_future(future)
