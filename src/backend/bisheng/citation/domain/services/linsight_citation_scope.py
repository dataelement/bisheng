"""Per-run citation bookkeeping for the Linsight task mode (F069).

One ``LinsightCitationScope`` lives for one session-version run inside the
Linsight worker process. The knowledge-base tool and the web-search wrapper
call :meth:`record_seen` every time they register retrieval hits, so the
completion-time audit can answer "how many sources did this run actually
see" — including hits made inside the researcher sub-graph, which the main
graph's ``values`` snapshots never observe (design §3 decision 3).

Redis is the durable copy (``linsight:cite_seen:<svid>``); the in-process set
is a mirror so the audit works even when Redis is unavailable. Nothing here
may raise into the agent loop: a Linsight tool exception kills the whole task
(F047 design §2), so every Redis call is fenced and degrades to a warning.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from bisheng.core.cache.redis_manager import get_redis_client

CITE_SEEN_KEY_PREFIX = "linsight:cite_seen:"
CITE_SEEN_TTL_SECONDS = 30 * 24 * 3600  # aligned with the citation runtime cache


class LinsightCitationScope:
    """Sources seen by one task-mode run, keyed by session-version id."""

    def __init__(self, svid: str, session_id: str, enabled: bool = True):
        self.svid = svid
        self.session_id = session_id
        self.enabled = enabled
        self.seen_keys: set[str] = set()

    @property
    def seen_redis_key(self) -> str:
        return f"{CITE_SEEN_KEY_PREFIX}{self.svid}"

    @staticmethod
    def _item_key(item: Any) -> str | None:
        key = getattr(item, "key", None)
        if key:
            return str(key)
        citation_id = getattr(item, "citationId", None)
        if not citation_id:
            return None
        item_id = getattr(item, "itemId", None)
        return f"{citation_id}:{item_id}" if item_id is not None else str(citation_id)

    @staticmethod
    def _item_type(item: Any) -> str:
        type_value = getattr(item, "type", None)
        return str(getattr(type_value, "value", type_value) or "")

    async def record_seen(self, items: list[Any] | None) -> None:
        """Remember every registry item this run has shown to the model."""
        mapping: dict[str, str] = {}
        for item in items or []:
            key = self._item_key(item)
            if not key or key in self.seen_keys:
                continue
            self.seen_keys.add(key)
            mapping[key] = self._item_type(item)
        if not mapping:
            return
        try:
            redis_client = await get_redis_client()
            await redis_client.ahset(self.seen_redis_key, mapping=mapping, expiration=CITE_SEEN_TTL_SECONDS)
            await redis_client.aexpire_key(self.seen_redis_key, CITE_SEEN_TTL_SECONDS)
        except Exception:
            logger.opt(exception=True).warning(
                f"linsight citation scope: failed to record {len(mapping)} seen sources svid={self.svid}"
            )

    async def load(self) -> None:
        """Hydrate the in-process mirror from Redis (resume / continue paths)."""
        try:
            redis_client = await get_redis_client()
            stored = await redis_client.ahgetall(self.seen_redis_key)
        except Exception:
            logger.opt(exception=True).warning(f"linsight citation scope: failed to load seen sources svid={self.svid}")
            return
        for key in (stored or {}).keys():
            if isinstance(key, bytes):
                key = key.decode("utf-8", errors="replace")
            if key:
                self.seen_keys.add(str(key))
