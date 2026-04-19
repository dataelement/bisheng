"""F015 Redis-backed store for multi-candidate relink conflicts.

Schema: ``HASH relink_conflict:{dept_id}`` whose fields are the
candidate ``new_external_id`` values and values are JSON payloads
``{"new_external_id": ..., "path": ..., "name": ..., "score": ...}``.
TTL defaults to 7 days (``settings.reconcile.relink_conflict_ttl_seconds``)
so forgotten conflicts evict themselves — re-running ``relink`` with the
same input rebuilds the entry.

Why Redis and not a table:

- Conflicts are ephemeral — admins are expected to resolve them within
  days via the ``resolve-conflict`` endpoint. Losing them is acceptable
  (just re-run the relink). A table would require a migration, a model,
  and a cleanup cron for little gain.
- The "set-or-replace" semantics for a single ``dept_id`` match a hash
  shape more cleanly than a table with a unique index.

The class is designed for trivial monkeypatching in tests (all methods
are classmethods that read ``get_redis_client`` on each call).
"""

from __future__ import annotations

import json
from typing import List, Optional

from loguru import logger

from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client


class RelinkConflictStore:
    """Short-lived storage of path_plus_name relink candidates."""

    KEY_PREFIX = 'relink_conflict:'

    @classmethod
    def _key(cls, dept_id: int) -> str:
        return f'{cls.KEY_PREFIX}{dept_id}'

    @classmethod
    async def save(cls, dept_id: int, candidates: List[dict]) -> None:
        """Overwrite the full candidate list for ``dept_id``.

        Empty ``candidates`` list is a no-op — callers guard for this
        before invoking, and we do not want to leave stale Redis keys
        just because an SSO migration produced no matches.
        """
        if not candidates:
            return
        redis = await get_redis_client()
        key = cls._key(dept_id)
        mapping = {
            str(c['new_external_id']): json.dumps(c, ensure_ascii=False)
            for c in candidates
        }
        await redis.async_connection.delete(key)  # ensure clean replace
        await redis.async_connection.hset(key, mapping=mapping)
        await redis.async_connection.expire(
            key, settings.reconcile.relink_conflict_ttl_seconds,
        )

    @classmethod
    async def get(cls, dept_id: int) -> List[dict]:
        """Return every candidate dict stored for ``dept_id`` (or [])."""
        redis = await get_redis_client()
        raw = await redis.async_connection.hgetall(cls._key(dept_id))
        if not raw:
            return []
        result: List[dict] = []
        for v in raw.values():
            # redis-py returns bytes under sync client, str under async —
            # cover both to stay resilient against client swaps.
            if isinstance(v, bytes):
                v = v.decode()
            try:
                result.append(json.loads(v))
            except Exception:
                logger.warning(
                    f'RelinkConflictStore: malformed JSON for dept {dept_id}')
        return result

    @classmethod
    async def delete(cls, dept_id: int) -> Optional[int]:
        """Drop the conflict entry (after a successful resolve)."""
        redis = await get_redis_client()
        return await redis.async_connection.delete(cls._key(dept_id))
