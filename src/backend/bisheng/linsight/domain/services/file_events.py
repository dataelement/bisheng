"""F004 T055: ``file`` events of a run (design §4.3, 决策 10; AC-24, AC-25).

A deliverable is a file under ``output/`` of the conversation workspace. Three
writers put files there, and all of them report through one callback:

* the file tools (``WorkspaceBackend.write`` / ``awrite`` / ``edit``);
* the code interpreter, when ``sync_to_workspace`` mirrored its files;
* the reconcile at the end of the run, for a file neither of the two reported.

The callback is a ``FileEventRelay``. The writers call it from the event loop or
from a worker thread; the relay writes the ``file`` event on the loop of the run.

``file_id`` is derived from the object key (``workspace_file_id``). The same path
always has the same id, so a second write updates the entry the client already
shows, and the id in the event equals the id stored on the answer row (F016).

State: the relay keeps what THIS execution announced. That is bookkeeping of one
execution in one process, like ``StreamEventMapper``'s context. The files of the
run are in the Redis snapshot; the files themselves are in object storage.
"""

from __future__ import annotations

import asyncio
import hashlib
import posixpath
import threading
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from bisheng.linsight.domain.schemas import run_events

OUTPUT_ZONE = "output/"

SOURCE_WRITE = "write_file"
SOURCE_EDIT = "edit_file"
SOURCE_CODE = "code_interpreter"
# Found by the reconcile at the end of the run.
SOURCE_RECONCILE = "workspace"
SOURCE_FINAL = "final_result"


def normalize_rel(rel_path: str) -> str:
    return (rel_path or "").replace("\\", "/").lstrip("/")


def is_deliverable_path(rel_path: str) -> bool:
    """True for a file under ``output/``. ``scratch/``, ``uploads/``, ``skills/`` are silent."""
    rel = normalize_rel(rel_path)
    if not rel.startswith(OUTPUT_ZONE) or rel.endswith("/"):
        return False
    parts = rel.split("/")
    return ".." not in parts and "" not in parts


def workspace_file_id(workspace_prefix: str, rel_path: str) -> str:
    """Stable id of one workspace file: the same object key always gives the same id."""
    key = f"{(workspace_prefix or '').strip('/')}/{normalize_rel(rel_path)}"
    return hashlib.md5(key.encode("utf-8")).hexdigest()[:16]


def workspace_object_key(workspace_prefix: str, rel_path: str) -> str:
    return f"{(workspace_prefix or '').strip('/')}/{normalize_rel(rel_path)}"


def file_event_data(workspace_prefix: str, rel_path: str, size: int | None, source: str) -> dict[str, Any]:
    """``data`` of a ``file`` event for one workspace file."""
    rel = normalize_rel(rel_path)
    data: dict[str, Any] = {
        "file_id": workspace_file_id(workspace_prefix, rel),
        "name": posixpath.basename(rel),
        "path": rel,
        "source": source,
    }
    if size is not None:
        data["size"] = int(size)
    return data


class FileEventRelay:
    """Write the ``file`` events of one execution. Callable from any thread.

    :param emit: async, writes one event of the run (stream and hooks).
    :param run_id: stamped on every event.
    :param workspace_prefix: object-key prefix of the workspace
        (``workspace/{conversation_id}``).

    Must be created on the event loop of the run.
    """

    def __init__(self, emit: Callable[[dict], Awaitable[None]], *, run_id: str | None, workspace_prefix: str):
        self._emit_event = emit
        self.run_id = run_id
        self.workspace_prefix = (workspace_prefix or "").strip("/")
        self._loop = asyncio.get_running_loop()
        self._lock = threading.Lock()
        self._pending: list[Any] = []
        # path -> data of the last event written for it, in first-seen order.
        self.announced: dict[str, dict[str, Any]] = {}
        # path -> signature of the ``output/`` files that existed before this
        # execution ran code. None until ``take_baseline``.
        self.baseline: dict[str, tuple] | None = None

    # -- writers -------------------------------------------------------------

    def __call__(self, data: dict[str, Any]) -> None:
        """Announce one file (``file_event_data``). Never raises; returns at once."""
        if not data or not is_deliverable_path(str(data.get("path") or "")):
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        try:
            if running is self._loop:
                future: Any = self._loop.create_task(self._announce(dict(data)))
            else:
                future = asyncio.run_coroutine_threadsafe(self._announce(dict(data)), self._loop)
        except RuntimeError:
            # The loop is closed: the run is over and nobody reads the event.
            logger.warning("file event for {} dropped: the run's event loop is closed", data.get("path"))
            return
        with self._lock:
            self._pending.append(future)

    def synced(self, rel_path: str, size: int | None = None) -> None:
        """The code interpreter mirrored ``rel_path`` into the workspace."""
        if is_deliverable_path(rel_path):
            self(file_event_data(self.workspace_prefix, rel_path, size, SOURCE_CODE))

    async def _announce(self, data: dict[str, Any]) -> None:
        try:
            await self._emit_event(run_events.make_event(run_events.FILE, data, run_id=self.run_id))
            self.announced[data["path"]] = data
        except Exception:
            # The file is stored; only its live notice is lost. The reconcile at
            # the end of the run announces it again.
            logger.exception("could not write the file event of {} run={}", data.get("path"), self.run_id)

    async def announce(self, data: dict[str, Any]) -> None:
        """Write one ``file`` event now (the caller is on the loop of the run)."""
        await self._announce(dict(data))

    async def drain(self) -> None:
        """Wait until every announced file has its event written."""
        while True:
            with self._lock:
                pending, self._pending = self._pending, []
            if not pending:
                return
            for future in pending:
                if not isinstance(future, asyncio.Future):
                    future = asyncio.wrap_future(future)
                # ``_announce`` logs its own failures; a cancelled one is not an error here.
                await asyncio.gather(future, return_exceptions=True)

    # -- reconcile -----------------------------------------------------------

    def take_baseline(self, listing: dict[str, tuple]) -> None:
        """Remember the ``output/`` files that exist before this execution writes any."""
        if self.baseline is None:
            self.baseline = dict(listing)

    async def reconcile(self, listing: dict[str, tuple]) -> int:
        """Announce the ``output/`` files of ``listing`` this execution changed but did not report.

        ``listing`` maps a workspace-relative path to ``(size, signature)``. A file
        that equals its baseline entry was left by an earlier run and is skipped.
        Returns how many events were written.
        """
        await self.drain()
        baseline = self.baseline or {}
        written = 0
        for rel, signature in listing.items():
            if not is_deliverable_path(rel):
                continue
            if baseline.get(rel) == signature:
                continue
            size = int(signature[0]) if signature and signature[0] is not None else None
            known = self.announced.get(rel)
            if known is not None and known.get("size") in (None, size):
                continue
            await self._announce(file_event_data(self.workspace_prefix, rel, size, SOURCE_RECONCILE))
            written += 1
        if written:
            logger.info("file reconcile: announced {} unreported file(s) run={}", written, self.run_id)
        return written
