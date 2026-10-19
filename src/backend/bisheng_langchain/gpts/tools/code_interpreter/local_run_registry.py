"""Retained run dirs of the isolated LocalExecutor, keyed by task workspace.

A Linsight task calls the code interpreter many times in the same workspace W.
Instead of claiming a uid and copying W in full on every call, the first call
claims a uid and a run dir R that are kept for the whole task; later calls only
copy what changed in W. ``release_local_run(W)`` gives both back when the task
ends, right before W itself is deleted.

Calls on one W are serialized: they share the uid, and the reap after one run
(``kill(-1)`` as that uid) would kill the other's processes. ``queue`` (asyncio)
orders waiting calls without holding a thread; ``inner`` (threading) is the real
mutual exclusion and stays held until the worker thread is done, even if the
awaiting coroutine was cancelled. Lock order is always queue, then inner;
``release_local_run`` only takes inner.

The registry is per process: a task runs in exactly one worker process.
"""

from __future__ import annotations

import asyncio
import os
import threading
from dataclasses import dataclass, field

from loguru import logger

from bisheng_langchain.gpts.tools.code_interpreter import local_uid_pool

# How long release waits for a call that is still running. The reap issued
# first makes that call return quickly; if it does not, the call frees the
# resources itself when it finishes.
RELEASE_WAIT_S = 30.0


@dataclass(eq=False)
class RunEntry:
    work_dir: str
    queue: asyncio.Lock = field(default_factory=asyncio.Lock)
    inner: threading.Lock = field(default_factory=threading.Lock)
    closing: bool = False
    uid: int | None = None
    run_dir: str | None = None
    run_root: str | None = None
    # {relative path: (size, mtime_ns)} of files on which R and W agree.
    index: dict[str, tuple[int, int]] = field(default_factory=dict)

    def acquire_inner(self) -> bool:
        """Wait for the inner lock; False (lock not taken) once the entry is closing."""
        while not self.inner.acquire(timeout=1.0):
            if self.closing:
                return False
        if self.closing:
            self.inner.release()
            return False
        return True


_registry: dict[str, RunEntry] = {}
_registry_lock = threading.Lock()


def _key(work_dir: str) -> str:
    return os.path.realpath(work_dir)


def register(work_dir: str) -> RunEntry:
    """Entry for ``work_dir``, created on first use. Called when the executor is built."""
    key = _key(work_dir)
    with _registry_lock:
        entry = _registry.get(key)
        if entry is None or entry.closing:
            entry = RunEntry(work_dir=key)
            _registry[key] = entry
        else:
            logger.warning("local isolation: workspace {} is already registered; sharing its run dir", key)
        return entry


def lookup(work_dir: str) -> RunEntry | None:
    with _registry_lock:
        return _registry.get(_key(work_dir))


def drop_resources(entry: RunEntry) -> None:
    """Reap the entry's uid and give uid and run dir back. Caller holds ``entry.inner``.

    If the reap cannot be confirmed the uid stays quarantined (marker kept, run
    dir kept) and is reclaimed by the startup sweep after the process restarts.
    """
    uid = entry.uid
    if uid is not None:
        if local_uid_pool.reap_uid(uid):
            local_uid_pool.free(uid, entry.run_root)
        else:
            logger.error("local isolation: uid {} of {} could not be reaped; kept quarantined", uid, entry.work_dir)
    entry.uid = None
    entry.run_dir = None
    entry.index = {}


def release_local_run(work_dir: str | None) -> None:
    """Free the retained run of ``work_dir``. No-op when nothing is registered.

    Blocking (kills processes, deletes a directory): call it from a thread.
    """
    if not work_dir:
        return
    key = _key(work_dir)
    with _registry_lock:
        entry = _registry.pop(key, None)
    if entry is None:
        return
    entry.closing = True
    if entry.uid is not None:
        # Ends a run that is still going, so the call holding inner returns soon.
        local_uid_pool.reap_uid(entry.uid)
    if not entry.inner.acquire(timeout=RELEASE_WAIT_S):
        logger.warning("local isolation: run in {} still busy at release; it frees its uid when done", key)
        return
    try:
        drop_resources(entry)
    finally:
        entry.inner.release()
