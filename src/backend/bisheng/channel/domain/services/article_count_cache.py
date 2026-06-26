"""ArticleCountCache — F040: short-TTL Redis cache for a channel's *main* article
count (the ``count_articles`` total for the channel's main filter rules).

Why this is cacheable (unlike per-user unread): the main article count depends only
on ``(channel source_list, main filter_rules)`` — it is identical for every user, so a
short TTL shared cache cuts the per-detail / per-square ES ``count`` round-trip without
serving stale-per-user data. Per-user unread counts are NOT cached here.

Key (tenant-isolated): ``article:count:{tenant_id}:channel:{channel_id}:main`` → int.

Fail-safe: every method swallows Redis errors and degrades to "miss" (get) / "no-op"
(set), so the caller always falls back to a live ES count — the cache never blocks the
main flow.
"""

from __future__ import annotations

from loguru import logger

KEY_PREFIX = "article:count:"
TTL = 120  # seconds — article ingestion is async (Celery); short staleness is acceptable.


def _tenant_id() -> int:
    from bisheng.core.context.tenant import get_current_tenant_id

    return get_current_tenant_id() or 1


def _main_key(tenant_id: int, channel_id: str) -> str:
    return f"{KEY_PREFIX}{tenant_id}:channel:{channel_id}:main"


async def _get_redis():
    try:
        from bisheng.core.cache.redis_manager import get_redis_client

        return await get_redis_client()
    except Exception as e:  # Redis unavailable — degrade to cache-miss, never block.
        logger.debug("ArticleCountCache: redis unavailable: {}", e)
        return None


class ArticleCountCache:
    """Stateless helper; all methods are @classmethod and fail-safe."""

    @classmethod
    async def get_main_count(cls, channel_id: str) -> int | None:
        """Cached main article count for one channel. ``None`` on miss / Redis down.

        Note: a cached value of ``0`` is a valid hit — callers must check ``is None``,
        not falsiness.
        """
        try:
            redis = await _get_redis()
            if redis is None:
                return None
            value = await redis.aget(_main_key(_tenant_id(), channel_id))
            return None if value is None else int(value)
        except Exception as e:
            logger.debug("ArticleCountCache.get_main_count error: {}", e)
            return None

    @classmethod
    async def set_main_count(cls, channel_id: str, count: int) -> None:
        try:
            redis = await _get_redis()
            if redis is None:
                return
            await redis.aset(_main_key(_tenant_id(), channel_id), int(count), expiration=TTL)
        except Exception as e:
            logger.debug("ArticleCountCache.set_main_count error: {}", e)

    @classmethod
    async def get_main_counts(cls, channel_ids: list[str]) -> dict[str, int]:
        """Batch variant: returns ``{channel_id: count}`` for cache *hits* only
        (missing / Redis-down channels are simply absent from the dict)."""
        result: dict[str, int] = {}
        if not channel_ids:
            return result
        try:
            redis = await _get_redis()
            if redis is None:
                return result
            tenant_id = _tenant_id()
            for cid in channel_ids:
                value = await redis.aget(_main_key(tenant_id, cid))
                if value is not None:
                    result[cid] = int(value)
        except Exception as e:
            logger.debug("ArticleCountCache.get_main_counts error: {}", e)
        return result

    @classmethod
    async def set_main_counts(cls, counts: dict[str, int]) -> None:
        if not counts:
            return
        try:
            redis = await _get_redis()
            if redis is None:
                return
            tenant_id = _tenant_id()
            for cid, count in counts.items():
                await redis.aset(_main_key(tenant_id, cid), int(count), expiration=TTL)
        except Exception as e:
            logger.debug("ArticleCountCache.set_main_counts error: {}", e)
