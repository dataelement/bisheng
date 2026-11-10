"""Enqueue gate for manual org sync — stops duplicate "run now" submissions.

``org_sync_config.sync_status`` is only set to ``running`` once the worker picks
the task up, so two clicks (or two admins) that land inside that window would
enqueue two tasks. This Redis NX lock closes that window: the API holds it from
``apply_async`` until the task's ``finally`` releases it.

The DB CAS in ``pull_sync_service`` stays as the execution-level guard (defence
in depth); this lock only prevents the wasted queue entry and the "22003 failed
task" noise in the worker log.

Fail-open: if Redis is unreachable the lock is skipped (log + continue) and the
DB CAS remains the sole guard, so the feature keeps working in a degraded
deployment.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from loguru import logger

from bisheng.core.cache.redis_manager import get_redis_client

KEY_TEMPLATE = "org_sync:enqueue:{config_id}"
# Longer than any realistic run; the task releases it early in `finally`.
DEFAULT_TTL_SECONDS = 30 * 60


@dataclass(frozen=True)
class EnqueueLock:
    """Result of the acquire attempt.

    ``acquired=False`` means a run is already queued/running.
    ``token=None`` with ``acquired=True`` means Redis was unavailable and the
    lock is degraded (nothing to release).
    """

    acquired: bool
    token: str | None


async def acquire_enqueue_lock(
    config_id: int,
    *,
    ttl: int = DEFAULT_TTL_SECONDS,
) -> EnqueueLock:
    token = uuid.uuid4().hex
    try:
        client = await get_redis_client()
        acquired = await client.async_connection.set(
            KEY_TEMPLATE.format(config_id=config_id),
            token,
            nx=True,
            ex=ttl,
        )
    except Exception:
        logger.exception(
            "org sync: enqueue lock unavailable (redis); falling back to the DB CAS guard for config_id={}",
            config_id,
        )
        return EnqueueLock(acquired=True, token=None)
    return EnqueueLock(acquired=bool(acquired), token=token if acquired else None)


async def is_enqueue_locked(config_id: int) -> bool:
    """True when a run is queued or in progress (the gate key still exists)."""
    try:
        client = await get_redis_client()
        return bool(await client.async_connection.get(KEY_TEMPLATE.format(config_id=config_id)))
    except Exception:
        logger.warning("org sync: cannot read the enqueue lock; assuming unlocked (config_id={})", config_id)
        return False


async def release_enqueue_lock(config_id: int, token: str | None) -> None:
    """Release only our own token (a TTL-expired lock may belong to a new run)."""
    if not token:
        return
    key = KEY_TEMPLATE.format(config_id=config_id)
    try:
        client = await get_redis_client()
        conn = client.async_connection
        current = await conn.get(key)
        if isinstance(current, bytes):
            current = current.decode()
        if current == token:
            await conn.delete(key)
    except Exception:
        logger.warning("org sync: failed to release enqueue lock for config_id={}", config_id)
