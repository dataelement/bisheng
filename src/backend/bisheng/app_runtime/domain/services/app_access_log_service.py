"""Access records as a side effect of the entry verdict (F054 AC-38, design D14-B).

``authorize_entry`` calls :func:`schedule_access_record` once it has decided
``allow`` and returns without waiting. The task then does two things, in this
order, and swallows whatever goes wrong in either:

1. ``SET app_access:{app_id}:{user_id} 1 NX EX <window>`` — atomically, not
   SETNX-then-EXPIRE (a crash between the two leaves a key with no TTL, which
   would merge that visitor's entries forever). A key that already exists means
   this entry is a repeat inside the merge window: no row.
2. ``INSERT INTO app_access_log`` with the application's tenant set
   explicitly — the internal endpoint runs under ``bypass_tenant_filter``, so
   the ``before_flush`` auto-fill is not there to do it.

**Why swallow.** The record is an audit asset, the verdict is the entry path
of every hosted application; a Redis blip or a slow insert must never keep a
visitor out, and must never be *seen* by app-proxy (whose contract is a
``decision`` field, nothing else). Redis being unreachable therefore writes
the row anyway — a duplicate inside the window is the cheaper failure than a
silent gap — while a failed insert is logged with its traceback and dropped.

**Why the task set.** ``asyncio.create_task`` keeps only a weak reference to
the task; without a strong one the loop may collect it mid-flight and the row
never lands, with nothing in the log. Same idiom as ``notification.forwarder``.
``flush_pending_access_records`` exists so tests (and a graceful shutdown) can
wait for the in-flight writes.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from loguru import logger

from bisheng.common.services.config_service import settings
from bisheng.core.database import get_async_db_session
from bisheng.database.models.app_access_log import AppAccessLog, AppAccessLogDao

#: Redis key of the merge window (design §6 key registry). One key per
#: ``(app, visitor)``; its TTL *is* the window.
ACCESS_DEDUP_KEY = "app_access:{app_id}:{user_id}"

# Strong references to in-flight writes — see the module docstring.
_pending_tasks: set[asyncio.Task] = set()


def schedule_access_record(
    *,
    app_id: str,
    tenant_id: int,
    user_id: int,
    user_name: str,
    request_id: str = "",
) -> asyncio.Task:
    """Fire-and-forget: schedule the record and return at once.

    Only ``entry_authz_service.authorize_entry`` calls this, and only on
    ``allow`` — the test ``test_scheduled_only_from_the_entry_verdict`` pins
    that down, because a second call site would be a second definition of
    what an "entry" is.
    """
    task = asyncio.create_task(
        record_access(
            app_id=app_id,
            tenant_id=tenant_id,
            user_id=user_id,
            user_name=user_name,
            request_id=request_id,
        )
    )
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)
    return task


async def record_access(
    *,
    app_id: str,
    tenant_id: int,
    user_id: int,
    user_name: str,
    request_id: str = "",
) -> bool:
    """Write one row unless this entry is a repeat inside the merge window.

    Returns ``True`` when a row was written. Never raises: every failure is
    logged here and ends here (see the module docstring for why).
    """
    try:
        if not await _first_entry_in_window(app_id=app_id, user_id=user_id):
            return False
        row = AppAccessLog(
            tenant_id=int(tenant_id),
            app_id=app_id,
            user_id=int(user_id),
            user_name=(user_name or "")[:128] or None,
            entry_time=datetime.now(),
            request_id=(request_id or "")[:64] or None,
        )
        async with get_async_db_session() as session:
            await AppAccessLogDao.ainsert(session, row)
            await session.commit()
        return True
    except Exception:
        # Best-effort by design (D14-B): the verdict has already been answered
        # and the record must never surface as an entry failure.
        logger.exception("app_runtime.access_log write failed app={} user={}", app_id, user_id)
        return False


async def _first_entry_in_window(*, app_id: str, user_id: int) -> bool:
    """``True`` when the merge-window key was just created — i.e. a new entry.

    Redis unreachable counts as a new entry: the alternative is dropping the
    record, and a duplicate row is the recoverable one of the two mistakes.
    """
    key = ACCESS_DEDUP_KEY.format(app_id=app_id, user_id=user_id)
    window = int(settings.app_runtime.access_log_merge_window_seconds)
    try:
        from bisheng.core.cache.redis_manager import get_redis_client

        client = await get_redis_client()
        created = await client.async_connection.set(key, b"1", nx=True, ex=window)
    except Exception as exc:
        logger.warning("app_runtime.access_log merge window unavailable ({}); recording without dedup", exc)
        return True
    return bool(created)


async def flush_pending_access_records() -> None:
    """Await every scheduled write. Failures were already handled inside each task."""
    if not _pending_tasks:
        return
    await asyncio.gather(*list(_pending_tasks), return_exceptions=True)
