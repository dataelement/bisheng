"""门户互动日统计与 Redis 合并队列实现。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, ClassVar

from elasticsearch import AsyncElasticsearch, NotFoundError

from bisheng.core.cache.redis_conn import RedisClient
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.knowledge.domain import knowledge_fulltext_constants as constants
from bisheng.knowledge.domain.repositories.interfaces.knowledge_fulltext_engagement_repository import (
    EngagementMetric,
    KnowledgeFulltextEngagementQueueRepository,
    KnowledgeFulltextEngagementRepository,
)
from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import (
    KnowledgeFulltextEngagementCounts,
    KnowledgeFulltextEngagementDaily,
    KnowledgeFulltextEngagementHistoryPage,
)

_EVENT_FIELDS = {
    "portal_document_read": (
        "event_data.portal_document_read_file_id",
        "event_data.portal_document_read_source_app.keyword",
        "event_data.portal_document_read_status.keyword",
        "preview_count",
    ),
    "portal_document_download": (
        "event_data.portal_document_download_file_id",
        "event_data.portal_document_download_source_app.keyword",
        "event_data.portal_document_download_status.keyword",
        "download_count",
    ),
}


class KnowledgeFulltextEngagementRepositoryImpl(KnowledgeFulltextEngagementRepository):
    _ready_daily_indices: ClassVar[set[tuple[int, str]]] = set()

    def __init__(
        self,
        *,
        daily_client: AsyncElasticsearch,
        raw_client: AsyncElasticsearch,
        daily_index: str = constants.KNOWLEDGE_FULLTEXT_ENGAGEMENT_DAILY_INDEX,
        raw_index: str = constants.KNOWLEDGE_FULLTEXT_ENGAGEMENT_RAW_INDEX,
    ):
        self.daily_client = daily_client
        self.raw_client = raw_client
        self.daily_index = daily_index
        self.raw_index = raw_index
        self._daily_index_ready = False

    async def _ensure_daily_index(self) -> None:
        readiness_key = (id(self.daily_client), self.daily_index)
        if self._daily_index_ready or readiness_key in self._ready_daily_indices:
            self._daily_index_ready = True
            return
        if self.daily_index != constants.KNOWLEDGE_FULLTEXT_ENGAGEMENT_DAILY_INDEX:
            self._daily_index_ready = True
            return
        from bisheng.telemetry.domain.mid_table.knowledge_space_content import KnowledgeSpaceContentStat

        mid_table = KnowledgeSpaceContentStat(ensure_sync_index=False)
        mid_table._es_client = self.daily_client
        await mid_table.ensure_index_exists()
        self._ready_daily_indices.add(readiness_key)
        self._daily_index_ready = True

    @staticmethod
    def daily_document_id(file_id: int, local_date: str) -> str:
        return f"portal_engagement_{file_id}_{local_date}"

    async def increment_daily(
        self,
        *,
        file_id: int,
        local_date: str,
        metric: EngagementMetric,
        updated_at: datetime,
    ) -> None:
        if metric not in {"preview_count", "download_count"}:
            raise ValueError(f"unsupported engagement metric: {metric}")
        await self._ensure_daily_index()
        upsert = {
            "record_type": "portal_engagement_daily",
            "file_id": str(file_id),
            "local_date": local_date,
            "preview_count": 1 if metric == "preview_count" else 0,
            "download_count": 1 if metric == "download_count" else 0,
            "projection_updated_at": int(updated_at.timestamp()),
        }
        await self.daily_client.update(
            index=self.daily_index,
            id=self.daily_document_id(file_id, local_date),
            retry_on_conflict=5,
            script={
                "lang": "painless",
                "source": (
                    f"ctx._source.{metric} = (ctx._source.{metric} ?: 0) + 1; "
                    "ctx._source.projection_updated_at = params.updated_at"
                ),
                "params": {"updated_at": int(updated_at.timestamp())},
            },
            upsert=upsert,
            refresh=False,
        )

    async def get_totals(self, file_ids: list[int]) -> dict[int, KnowledgeFulltextEngagementCounts]:
        normalized = list(dict.fromkeys(int(item) for item in file_ids if int(item) > 0))
        result = {file_id: KnowledgeFulltextEngagementCounts(file_id=file_id) for file_id in normalized}
        if not normalized:
            return result
        try:
            response = await self.daily_client.search(
                index=self.daily_index,
                size=0,
                query={
                    "bool": {
                        "filter": [
                            {"term": {"record_type": "portal_engagement_daily"}},
                            {"terms": {"file_id": [str(file_id) for file_id in normalized]}},
                        ]
                    }
                },
                aggs={
                    "by_file": {
                        "terms": {"field": "file_id", "size": len(normalized)},
                        "aggs": {
                            "preview_total": {"sum": {"field": "preview_count"}},
                            "download_total": {"sum": {"field": "download_count"}},
                        },
                    }
                },
            )
        except NotFoundError:
            return result
        buckets = response.get("aggregations", {}).get("by_file", {}).get("buckets", [])
        for bucket in buckets:
            try:
                file_id = int(bucket.get("key"))
            except (TypeError, ValueError):
                continue
            if file_id not in result:
                continue
            result[file_id] = KnowledgeFulltextEngagementCounts(
                file_id=file_id,
                preview_count=int(bucket.get("preview_total", {}).get("value") or 0),
                download_count=int(bucket.get("download_total", {}).get("value") or 0),
            )
        return result

    async def aggregate_history_page(
        self,
        *,
        event_type: str,
        after_key: dict[str, Any] | None,
        page_size: int,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> KnowledgeFulltextEngagementHistoryPage:
        try:
            file_field, source_field, status_field, metric = _EVENT_FIELDS[event_type]
        except KeyError as exc:
            raise ValueError(f"unsupported engagement event type: {event_type}") from exc
        filters: list[dict[str, Any]] = [
            {"term": {"event_type": event_type}},
            {"term": {source_field: "shougang_portal"}},
            {"term": {status_field: "success"}},
        ]
        if start_at is not None or end_at is not None:
            timestamp_range: dict[str, Any] = {}
            if start_at is not None:
                timestamp_range["gte"] = int(start_at.timestamp())
            if end_at is not None:
                timestamp_range["lt"] = int(end_at.timestamp())
            filters.append({"range": {"timestamp": timestamp_range}})
        composite: dict[str, Any] = {
            "size": max(1, int(page_size)),
            "sources": [
                {"file_id": {"terms": {"field": file_field}}},
                {
                    "local_date": {
                        "date_histogram": {
                            "field": "timestamp",
                            "calendar_interval": "1d",
                            "time_zone": "+08:00",
                            "format": "yyyy-MM-dd",
                        }
                    }
                },
            ],
        }
        if after_key:
            composite["after"] = after_key
        try:
            response = await self.raw_client.search(
                index=self.raw_index,
                size=0,
                query={"bool": {"filter": filters}},
                aggs={"daily": {"composite": composite}},
            )
        except NotFoundError:
            return KnowledgeFulltextEngagementHistoryPage()
        aggregation = response.get("aggregations", {}).get("daily", {})
        records: list[KnowledgeFulltextEngagementDaily] = []
        for bucket in aggregation.get("buckets", []):
            key = bucket.get("key") or {}
            try:
                file_id = int(key.get("file_id"))
                local_date = str(key.get("local_date"))
                count = int(bucket.get("doc_count") or 0)
            except (TypeError, ValueError):
                continue
            if file_id <= 0 or count < 0:
                continue
            values = {"file_id": file_id, "local_date": local_date, metric: count}
            records.append(KnowledgeFulltextEngagementDaily(**values))
        return KnowledgeFulltextEngagementHistoryPage(
            records=records,
            after_key=aggregation.get("after_key"),
        )

    async def set_daily_metric(
        self,
        records: list[KnowledgeFulltextEngagementDaily],
        *,
        metric: EngagementMetric,
        updated_at: datetime,
    ) -> list[int]:
        if not records:
            return []
        await self._ensure_daily_index()
        operations: list[dict[str, Any]] = []
        for record in records:
            value = getattr(record, metric)
            operations.extend(
                [
                    {
                        "update": {
                            "_index": self.daily_index,
                            "_id": self.daily_document_id(record.file_id, record.local_date),
                            "retry_on_conflict": 5,
                        }
                    },
                    {
                        "scripted_upsert": True,
                        "script": {
                            "lang": "painless",
                            "source": (
                                f"if (ctx.op != 'create' && "
                                f"(ctx._source.{metric} ?: 0) == params.value) {{ ctx.op = 'noop'; }} "
                                f"else {{ ctx._source.{metric} = params.value; "
                                "ctx._source.projection_updated_at = params.updated_at; }"
                            ),
                            "params": {"value": value, "updated_at": int(updated_at.timestamp())},
                        },
                        "upsert": {
                            "record_type": "portal_engagement_daily",
                            "file_id": str(record.file_id),
                            "local_date": record.local_date,
                            "preview_count": record.preview_count,
                            "download_count": record.download_count,
                            "projection_updated_at": int(updated_at.timestamp()),
                        },
                    },
                ]
            )
        response = await self.daily_client.bulk(operations=operations, refresh=False)
        changed: list[int] = []
        failures: list[int] = []
        for item in response.get("items", []):
            update = item.get("update") or {}
            try:
                file_id = int(str(update.get("_id")).split("_")[2])
            except (IndexError, TypeError, ValueError):
                continue
            status = int(update.get("status") or 0)
            if status >= 300:
                failures.append(file_id)
            elif update.get("result") != "noop":
                changed.append(file_id)
        if failures:
            raise RuntimeError(f"failed to merge {len(failures)} engagement daily records")
        return list(dict.fromkeys(changed))

    async def refresh_daily(self) -> None:
        await self._ensure_daily_index()
        await self.daily_client.indices.refresh(index=self.daily_index)


class KnowledgeFulltextEngagementQueueRepositoryImpl(KnowledgeFulltextEngagementQueueRepository):
    HASH_TAG = "{knowledge_fulltext_engagement}"
    PREFIX = f"knowledge_fulltext_engagement:{HASH_TAG}"
    PENDING_KEY = f"{PREFIX}:pending"
    PROCESSING_KEY = f"{PREFIX}:processing"
    PROCESSING_OWNER_KEY = f"{PREFIX}:processing_owner"
    SCHEDULE_KEY = f"{PREFIX}:scheduled"
    HISTORY_LOCK_KEY = f"{PREFIX}:history_lock"
    HISTORY_CURSOR_PREFIX = f"{PREFIX}:history_cursor"

    CLAIM_SCRIPT = """
local members = redis.call('zrangebyscore', KEYS[1], '-inf', ARGV[1], 'LIMIT', 0, ARGV[4])
local claimed = {}
for _, member in ipairs(members) do
  if redis.call('zrem', KEYS[1], member) == 1 then
    redis.call('zadd', KEYS[2], ARGV[2], member)
    redis.call('hset', KEYS[3], member, ARGV[3])
    table.insert(claimed, member)
  end
end
return claimed
"""
    ACK_SCRIPT = """
if redis.call('hget', KEYS[2], ARGV[1]) ~= ARGV[2] then return 0 end
redis.call('zrem', KEYS[1], ARGV[1])
redis.call('hdel', KEYS[2], ARGV[1])
return 1
"""
    RETRY_SCRIPT = """
if redis.call('hget', KEYS[3], ARGV[1]) ~= ARGV[2] then return 0 end
redis.call('zrem', KEYS[2], ARGV[1])
redis.call('hdel', KEYS[3], ARGV[1])
redis.call('zadd', KEYS[1], 'NX', ARGV[3], ARGV[1])
return 1
"""
    RECLAIM_SCRIPT = """
local members = redis.call('zrangebyscore', KEYS[2], '-inf', ARGV[1])
for _, member in ipairs(members) do
  redis.call('zadd', KEYS[1], 'NX', ARGV[1], member)
  redis.call('zrem', KEYS[2], member)
  redis.call('hdel', KEYS[3], member)
end
return #members
"""
    RELEASE_LOCK_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end
return 0
"""

    def __init__(
        self,
        *,
        redis_client: RedisClient | Any | None = None,
        delay_seconds: int = constants.KNOWLEDGE_FULLTEXT_ENGAGEMENT_DELAY_SECONDS,
        lease_seconds: int = constants.KNOWLEDGE_FULLTEXT_ENGAGEMENT_LEASE_SECONDS,
    ):
        self.redis_client = redis_client
        self.delay_seconds = max(1, int(delay_seconds))
        self.lease_seconds = max(1, int(lease_seconds))

    async def _connection(self):
        if self.redis_client is None:
            self.redis_client = await get_redis_client()
        return self.redis_client.async_connection

    async def enqueue(self, *, file_id: int, now_epoch: int) -> bool:
        redis = await self._connection()
        return bool(
            await redis.zadd(
                self.PENDING_KEY,
                {str(file_id): int(now_epoch) + self.delay_seconds},
                nx=True,
            )
        )

    async def claim(self, *, now_epoch: int, lease_owner: str, limit: int) -> list[int]:
        redis = await self._connection()
        values = await redis.eval(
            self.CLAIM_SCRIPT,
            3,
            self.PENDING_KEY,
            self.PROCESSING_KEY,
            self.PROCESSING_OWNER_KEY,
            int(now_epoch),
            int(now_epoch) + self.lease_seconds,
            lease_owner,
            max(1, int(limit)),
        )
        return [int(value) for value in values]

    async def ack(self, *, file_id: int, lease_owner: str) -> bool:
        redis = await self._connection()
        result = await redis.eval(
            self.ACK_SCRIPT,
            2,
            self.PROCESSING_KEY,
            self.PROCESSING_OWNER_KEY,
            str(file_id),
            lease_owner,
        )
        return bool(result)

    async def retry(self, *, file_id: int, lease_owner: str, now_epoch: int) -> bool:
        redis = await self._connection()
        result = await redis.eval(
            self.RETRY_SCRIPT,
            3,
            self.PENDING_KEY,
            self.PROCESSING_KEY,
            self.PROCESSING_OWNER_KEY,
            str(file_id),
            lease_owner,
            int(now_epoch) + self.delay_seconds,
        )
        return bool(result)

    async def reclaim_expired(self, *, now_epoch: int) -> int:
        redis = await self._connection()
        return int(
            await redis.eval(
                self.RECLAIM_SCRIPT,
                3,
                self.PENDING_KEY,
                self.PROCESSING_KEY,
                self.PROCESSING_OWNER_KEY,
                int(now_epoch),
            )
        )

    async def acquire_schedule(self) -> bool:
        redis = await self._connection()
        return bool(
            await redis.set(
                self.SCHEDULE_KEY,
                "1",
                nx=True,
                ex=self.delay_seconds,
            )
        )

    async def release_schedule(self) -> None:
        redis = await self._connection()
        await redis.delete(self.SCHEDULE_KEY)

    async def acquire_history_lock(self, token: str) -> bool:
        redis = await self._connection()
        return bool(
            await redis.set(
                self.HISTORY_LOCK_KEY,
                token,
                nx=True,
                ex=constants.KNOWLEDGE_FULLTEXT_ENGAGEMENT_HISTORY_LOCK_SECONDS,
            )
        )

    async def release_history_lock(self, token: str) -> bool:
        redis = await self._connection()
        return bool(
            await redis.eval(
                self.RELEASE_LOCK_SCRIPT,
                1,
                self.HISTORY_LOCK_KEY,
                token,
            )
        )

    @classmethod
    def _cursor_key(cls, stage: str) -> str:
        return f"{cls.HISTORY_CURSOR_PREFIX}:{stage}"

    async def load_history_cursor(self, stage: str) -> dict[str, Any] | None:
        redis = await self._connection()
        value = await redis.get(self._cursor_key(stage))
        if value is None:
            return None
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        decoded = json.loads(value)
        return decoded if isinstance(decoded, dict) else None

    async def save_history_cursor(self, stage: str, cursor: dict[str, Any] | None) -> None:
        redis = await self._connection()
        key = self._cursor_key(stage)
        if cursor is None:
            await redis.delete(key)
            return
        await redis.set(key, json.dumps(cursor, ensure_ascii=True, separators=(",", ":")))

    async def clear_history_state(self) -> None:
        redis = await self._connection()
        await redis.delete(
            self._cursor_key("portal_document_read"),
            self._cursor_key("portal_document_download"),
            self._cursor_key("fulltext"),
        )
