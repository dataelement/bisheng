from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar, Literal

from elasticsearch import helpers
from loguru import logger
from pydantic import BaseModel, Field

from bisheng.common.constants.telemetry import KNOWLEDGE_SPACE_CONTENT_STAT_INDEX
from bisheng.core.cache.redis_manager import get_redis_client, get_redis_client_sync
from bisheng.knowledge.domain.constants import (
    BUSINESS_DOMAIN_OPTIONS,
    get_business_domain_code_from_file,
    get_file_category_code_from_file,
    normalize_file_category_code,
)
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.telemetry.domain.mid_table.base import BaseMidTable
from bisheng.telemetry.domain.mid_table.knowledge_space_content_dimensions import (
    CONTENT_DIMENSION_FIELDS,
    OrganizationNameSnapshot,
    build_daily_document_id,
)
from bisheng.utils import generate_uuid

CHINA_STANDARD_TIME = timezone(timedelta(hours=8))

SPACE_LEVEL_LABELS = {
    "public": "公共库",
    "department": "部门库",
    "team": "团队库",
    "team_ks": "科室库",
    "personal": "个人库",
    "unknown": "未分类知识库",
}


class KnowledgeSpaceContentRecord(BaseModel):
    """Current file projection stored in the dashboard statistics index."""

    es_id: str | None = Field(default=None)
    record_type: str = "file"
    sync_run_id: str | None = None
    timestamp: int
    space_id: int
    space_name: str
    space_level: str = "unknown"
    space_level_name: str = SPACE_LEVEL_LABELS["unknown"]
    file_id: int
    file_name: str
    file_type: int
    file_category_code: str | None = None
    file_category_name: str | None = None
    file_subcategory_code: str | None = None
    file_subcategory_name: str | None = None
    business_domain_code: str | None = None
    business_domain_name: str | None = None
    projection_updated_at: int | None = None
    uploader_user_id: int
    uploader_user_name: str
    uploader_company_name: str | None = None
    uploader_department_name: str | None = None
    uploader_office_name: str | None = None
    uploader_squad_name: str | None = None
    belonging_company_name: str | None = None
    belonging_department_name: str | None = None
    belonging_office_name: str | None = None
    belonging_squad_name: str | None = None
    # 原始上传库XX (2026-09-01): 库->组织映射规则同 belonging_*, but evaluated against the
    # file's ORIGINAL upload space (KnowledgeFile.original_knowledge_id, F081) and frozen
    # forever once set — never recomputed from who currently holds the file or their
    # department. Kept separate from uploader_* (which stays on its original "current
    # uploader's current department" logic, per product's own naming/semantics).
    original_upload_company_name: str | None = None
    original_upload_department_name: str | None = None
    original_upload_office_name: str | None = None
    original_upload_squad_name: str | None = None

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("exclude_none", True)
        return super().model_dump(*args, **kwargs)


class KnowledgeSpacePreviewDailyRecord(KnowledgeSpaceContentRecord):
    record_type: Literal["preview_daily"] = "preview_daily"
    local_date: str
    preview_count: int = Field(ge=0)


class KnowledgeSpaceDownloadDailyRecord(KnowledgeSpaceContentRecord):
    """Daily portal download aggregate enriched with the current file dimensions."""

    record_type: Literal["download_daily"] = "download_daily"
    local_date: str
    download_count: int = Field(ge=0)


class KnowledgeSpaceFavoriteDailyRecord(KnowledgeSpaceContentRecord):
    record_type: Literal["favorite_daily"] = "favorite_daily"
    local_date: str
    favorite_count: int = Field(ge=0)


@dataclass(frozen=True)
class ProjectionWorkItem:
    member: str
    enqueued_at_ms: int

    @property
    def kind(self) -> str:
        return self.member.partition(":")[0]

    @property
    def resource_id(self) -> int:
        return int(self.member.partition(":")[2])


class ContentStatEventEnvelope(BaseModel):
    event_id: str
    event_type: str
    record_type: str
    user_id: int
    occurred_at: int
    local_date: str
    daily_id: str
    source_app: str
    scene: str
    entry_point: str
    dimensions: dict[str, Any]


class KnowledgeSpaceContentStat(BaseMidTable):
    INDEX_NAME: ClassVar[str] = KNOWLEDGE_SPACE_CONTENT_STAT_INDEX
    _index_name: str = KNOWLEDGE_SPACE_CONTENT_STAT_INDEX
    _update_mappings_on_existing: bool = True
    _include_common_mappings: bool = False
    _refresh_settings_applied: ClassVar[set[str]] = set()

    REDIS_HASH_TAG: ClassVar[str] = "{knowledge_space_content}"
    PENDING_KEY: ClassVar[str] = f"telemetry:{REDIS_HASH_TAG}:pending"
    PROCESSING_KEY: ClassVar[str] = f"telemetry:{REDIS_HASH_TAG}:processing"
    PROCESSING_META_KEY: ClassVar[str] = f"telemetry:{REDIS_HASH_TAG}:processing_meta"
    SCHEDULED_KEY: ClassVar[str] = f"telemetry:{REDIS_HASH_TAG}:scheduled"
    LOCK_KEY: ClassVar[str] = f"telemetry:{REDIS_HASH_TAG}:owner_lock"
    EVENT_PENDING_KEY: ClassVar[str] = f"telemetry:{REDIS_HASH_TAG}:event_pending"
    EVENT_PROCESSING_KEY: ClassVar[str] = f"telemetry:{REDIS_HASH_TAG}:event_processing"
    EVENT_PROCESSING_META_KEY: ClassVar[str] = f"telemetry:{REDIS_HASH_TAG}:event_processing_meta"
    EVENT_PAYLOAD_KEY: ClassVar[str] = f"telemetry:{REDIS_HASH_TAG}:event_payload"
    EVENT_SCHEDULED_KEY: ClassVar[str] = f"telemetry:{REDIS_HASH_TAG}:event_scheduled"
    REPLAY_FLOOR_KEY: ClassVar[str] = f"telemetry:{REDIS_HASH_TAG}:replay_floor"

    # Exact legacy keys are retained only for rebuild preflight and cleanup reporting.
    LEGACY_FILE_PENDING_KEY: ClassVar[str] = "telemetry:knowledge_space_content:file_pending"
    LEGACY_PREVIEW_PENDING_KEY: ClassVar[str] = "telemetry:knowledge_space_content:preview_pending"
    LEGACY_SPACE_RENAME_PENDING_KEY: ClassVar[str] = "telemetry:knowledge_space_content:space_rename_pending"
    LEGACY_SPACE_DELETE_PENDING_KEY: ClassVar[str] = "telemetry:knowledge_space_content:space_delete_pending"
    LEGACY_SCHEDULED_KEY: ClassVar[str] = "telemetry:knowledge_space_content:scheduled"
    LEGACY_LOCK_KEY: ClassVar[str] = "telemetry:knowledge_space_content:lock"

    SCHEDULE_DELAY_SECONDS: ClassVar[int] = 2
    SCHEDULE_TTL_SECONDS: ClassVar[int] = 5
    LOCK_TTL_SECONDS: ClassVar[int] = 300
    PROCESSING_LEASE_SECONDS: ClassVar[int] = 240
    FILE_BATCH_SIZE: ClassVar[int] = 500

    CLAIM_SCRIPT: ClassVar[str] = """
if redis.call('get', KEYS[4]) ~= ARGV[1] then
  return {}
end
local values = redis.call('zrange', KEYS[1], 0, tonumber(ARGV[4]) - 1, 'withscores')
local claimed = {}
for index = 1, #values, 2 do
  local member = values[index]
  local enqueued_at = values[index + 1]
  if redis.call('zrem', KEYS[1], member) == 1 then
    redis.call('zadd', KEYS[2], ARGV[3], member)
    redis.call('hset', KEYS[3], member, enqueued_at)
    table.insert(claimed, member)
    table.insert(claimed, enqueued_at)
  end
end
return claimed
"""
    ACK_SCRIPT: ClassVar[str] = """
if redis.call('get', KEYS[3]) ~= ARGV[1] then
  return 0
end
local removed = 0
for index = 2, #ARGV do
  removed = removed + redis.call('zrem', KEYS[1], ARGV[index])
  redis.call('hdel', KEYS[2], ARGV[index])
end
return removed
"""
    RENEW_CLAIMS_SCRIPT: ClassVar[str] = """
if redis.call('get', KEYS[2]) ~= ARGV[1] then
  return 0
end
local renewed = 0
for index = 3, #ARGV do
  if redis.call('zscore', KEYS[1], ARGV[index]) then
    redis.call('zadd', KEYS[1], ARGV[2], ARGV[index])
    renewed = renewed + 1
  end
end
return renewed
"""
    RECLAIM_SCRIPT: ClassVar[str] = """
local expired = redis.call('zrangebyscore', KEYS[2], '-inf', ARGV[1])
local reclaimed = 0
for _, member in ipairs(expired) do
  local enqueued_at = redis.call('hget', KEYS[3], member) or ARGV[1]
  redis.call('zadd', KEYS[1], 'NX', enqueued_at, member)
  redis.call('zrem', KEYS[2], member)
  redis.call('hdel', KEYS[3], member)
  reclaimed = reclaimed + 1
end
return reclaimed
"""
    RENEW_LOCK_SCRIPT: ClassVar[str] = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""
    RELEASE_LOCK_SCRIPT: ClassVar[str] = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""
    ACK_EVENT_SCRIPT: ClassVar[str] = """
if redis.call('get', KEYS[4]) ~= ARGV[1] then
  return 0
end
local removed = 0
for index = 2, #ARGV do
  removed = removed + redis.call('zrem', KEYS[1], ARGV[index])
  redis.call('hdel', KEYS[2], ARGV[index])
  redis.call('hdel', KEYS[3], ARGV[index])
end
return removed
"""

    _mappings: dict[str, Any] = {
        "record_type": {"type": "keyword"},
        "sync_run_id": {"type": "keyword"},
        "timestamp": {
            "type": "date",
            "format": "strict_date_optional_time||epoch_second",
        },
        "local_date": {"type": "keyword"},
        "preview_count": {"type": "long"},
        "download_count": {"type": "long"},
        "favorite_count": {"type": "long"},
        "space_id": {"type": "keyword", "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}}},
        "space_name": {"type": "keyword", "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}}},
        "space_level": {"type": "keyword"},
        "space_level_name": {
            "type": "keyword",
            "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}},
        },
        "file_id": {"type": "keyword", "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}}},
        "file_name": {"type": "keyword", "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}}},
        "file_type": {"type": "integer"},
        "file_category_code": {"type": "keyword"},
        "file_category_name": {
            "type": "keyword",
            "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}},
        },
        "file_subcategory_code": {"type": "keyword"},
        "file_subcategory_name": {
            "type": "keyword",
            "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}},
        },
        "business_domain_code": {"type": "keyword"},
        "business_domain_name": {
            "type": "keyword",
            "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}},
        },
        "projection_updated_at": {"type": "date", "format": "strict_date_optional_time||epoch_second"},
        "uploader_user_id": {
            "type": "keyword",
            "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}},
        },
        "uploader_user_name": {
            "type": "keyword",
            "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}},
        },
        **{
            field: {
                "type": "keyword",
                "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}},
            }
            for field in (
                "uploader_company_name",
                "uploader_department_name",
                "uploader_office_name",
                "uploader_squad_name",
                "belonging_company_name",
                "belonging_department_name",
                "belonging_office_name",
                "belonging_squad_name",
                "original_upload_company_name",
                "original_upload_department_name",
                "original_upload_office_name",
                "original_upload_squad_name",
            )
        },
    }

    PREVIEW_DIMENSION_FIELDS: ClassVar[tuple[str, ...]] = CONTENT_DIMENSION_FIELDS

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)

    @staticmethod
    def _normalize_ids(ids: Iterable[int]) -> list[int]:
        normalized: list[int] = []
        seen: set[int] = set()
        for raw_id in ids or []:
            if raw_id is None:
                continue
            try:
                item_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if item_id <= 0 or item_id in seen:
                continue
            seen.add(item_id)
            normalized.append(item_id)
        return normalized

    @staticmethod
    def _decode_text(value: Any) -> str | None:
        if value is None:
            return None
        return value.decode("utf-8") if isinstance(value, bytes) else str(value)

    @classmethod
    def _work_members(cls, kind: str, ids: Iterable[int]) -> list[str]:
        return [f"{kind}:{item_id}" for item_id in cls._normalize_ids(ids)]

    @classmethod
    def _apply_refresh_setting_sync(cls, instance: KnowledgeSpaceContentStat) -> None:
        if cls.INDEX_NAME in cls._refresh_settings_applied:
            return
        instance._es_client_sync.indices.put_settings(
            index=cls.INDEX_NAME,
            settings={"index": {"refresh_interval": "1s"}},
        )
        cls._refresh_settings_applied.add(cls.INDEX_NAME)

    @classmethod
    def reset_index_bootstrap_state(cls) -> None:
        """Forget process-local index bootstrap caches after an explicit delete."""
        cls._refresh_settings_applied.discard(cls.INDEX_NAME)
        cls._mapping_updates_applied.discard(cls.INDEX_NAME)

    async def ensure_index_exists(self) -> None:
        await super().ensure_index_exists()
        if self.INDEX_NAME not in self._refresh_settings_applied:
            await self._es_client.indices.put_settings(
                index=self.INDEX_NAME,
                settings={"index": {"refresh_interval": "1s"}},
            )
            self._refresh_settings_applied.add(self.INDEX_NAME)

    def ensure_index_exists_sync(self) -> None:
        super().ensure_index_exists_sync()
        self._apply_refresh_setting_sync(self)

    @classmethod
    def _zadd_pending_sync(cls, redis_client, members: Iterable[str], *, now_ms: int | None = None) -> None:
        mapping = {member: now_ms or cls._now_ms() for member in members if member}
        if not mapping:
            return
        redis_client.cluster_nodes(cls.PENDING_KEY)
        redis_client.connection.zadd(cls.PENDING_KEY, mapping, nx=True)

    @classmethod
    async def _zadd_pending_async(cls, redis_client, members: Iterable[str], *, now_ms: int | None = None) -> None:
        mapping = {member: now_ms or cls._now_ms() for member in members if member}
        if not mapping:
            return
        await redis_client.acluster_nodes(cls.PENDING_KEY)
        await redis_client.async_connection.zadd(cls.PENDING_KEY, mapping, nx=True)

    @classmethod
    def _schedule_pending_sync(cls, redis_client=None, *, countdown: int = SCHEDULE_DELAY_SECONDS) -> None:
        redis_client = redis_client or get_redis_client_sync()
        if not redis_client.setNx(cls.SCHEDULED_KEY, 1, expiration=cls.SCHEDULE_TTL_SECONDS):
            return
        from bisheng.worker.telemetry.mid_table import sync_pending_knowledge_space_content_stat

        sync_pending_knowledge_space_content_stat.apply_async(countdown=countdown)

    @classmethod
    async def _schedule_pending_async(cls, redis_client=None, *, countdown: int = SCHEDULE_DELAY_SECONDS) -> None:
        redis_client = redis_client or await get_redis_client()
        if not await redis_client.asetNx(cls.SCHEDULED_KEY, 1, expiration=cls.SCHEDULE_TTL_SECONDS):
            return
        from bisheng.worker.telemetry.mid_table import sync_pending_knowledge_space_content_stat

        sync_pending_knowledge_space_content_stat.apply_async(countdown=countdown)

    @classmethod
    async def _schedule_event_pending_async(
        cls,
        redis_client=None,
        *,
        countdown: int = SCHEDULE_DELAY_SECONDS,
    ) -> None:
        redis_client = redis_client or await get_redis_client()
        if not await redis_client.asetNx(
            cls.EVENT_SCHEDULED_KEY,
            1,
            expiration=cls.SCHEDULE_TTL_SECONDS,
        ):
            return
        from bisheng.worker.telemetry.mid_table import sync_pending_knowledge_space_content_events

        sync_pending_knowledge_space_content_events.apply_async(countdown=countdown)

    @classmethod
    async def enqueue_success_event_async(
        cls,
        *,
        file_id: int,
        user_id: int,
        event_type: str,
        record_type: str,
        source_app: str,
        scene: str,
        entry_point: str,
        occurred_at: datetime | None = None,
    ) -> bool:
        """Capture fresh dimensions and durably queue one successful action."""
        try:
            from bisheng.worker.telemetry.mid_table import build_knowledge_space_content_event_record

            record = await asyncio.to_thread(
                build_knowledge_space_content_event_record,
                int(file_id),
            )
            if record is None:
                return False
            local_time = (occurred_at or datetime.now(CHINA_STANDARD_TIME)).astimezone(CHINA_STANDARD_TIME)
            dimensions = {
                field: getattr(record, field)
                for field in CONTENT_DIMENSION_FIELDS
                if getattr(record, field) is not None
            }
            local_date = local_time.date().isoformat()
            daily_id = build_daily_document_id(
                record_type=record_type,
                file_id=int(file_id),
                local_date=local_date,
                dimensions=dimensions,
            )
            event_id = generate_uuid()
            envelope = ContentStatEventEnvelope(
                event_id=event_id,
                event_type=event_type,
                record_type=record_type,
                user_id=int(user_id),
                occurred_at=int(local_time.timestamp()),
                local_date=local_date,
                daily_id=daily_id,
                source_app=source_app,
                scene=scene,
                entry_point=entry_point,
                dimensions=dimensions,
            )
            redis_client = await get_redis_client()
            await redis_client.acluster_nodes(cls.EVENT_PENDING_KEY)
            await redis_client.async_connection.hset(
                cls.EVENT_PAYLOAD_KEY,
                event_id,
                envelope.model_dump_json(),
            )
            await redis_client.async_connection.zadd(
                cls.EVENT_PENDING_KEY,
                {event_id: cls._now_ms()},
                nx=True,
            )
            await cls._schedule_event_pending_async(redis_client)
            return True
        except Exception:
            logger.exception(
                "Knowledge space content event enqueue failed. degraded=true file_id={} record_type={}",
                file_id,
                record_type,
            )
            return False

    @classmethod
    def enqueue_file_stat_sync(cls, file_ids: Iterable[int]) -> bool:
        members = cls._work_members("file", file_ids)
        if not members:
            return True
        try:
            redis_client = get_redis_client_sync()
            cls._zadd_pending_sync(redis_client, members)
            cls._schedule_pending_sync(redis_client)
            return True
        except Exception:
            logger.exception(
                "Knowledge space content projection enqueue failed. degraded=true failure_stage=enqueue operation=file ids={}",
                file_ids,
            )
            return False

    @classmethod
    async def enqueue_file_stat_async(cls, file_ids: Iterable[int]) -> bool:
        normalized_ids = cls._normalize_ids(file_ids)
        members = cls._work_members("file", normalized_ids)
        if not members:
            return True
        try:
            redis_client = await get_redis_client()
            await cls._zadd_pending_async(redis_client, members)
            await cls._schedule_pending_async(redis_client)
            return True
        except Exception:
            logger.exception(
                "Knowledge space content projection enqueue failed. degraded=true failure_stage=enqueue operation=file ids={}",
                normalized_ids,
            )
            return False

    @classmethod
    async def _enqueue_space_stat_async(cls, space_id: int) -> bool:
        ids = cls._normalize_ids([space_id])
        if not ids:
            return True
        try:
            redis_client = await get_redis_client()
            await cls._zadd_pending_async(redis_client, cls._work_members("space", ids))
            await cls._schedule_pending_async(redis_client)
            return True
        except Exception:
            logger.exception(
                "Knowledge space content projection enqueue failed. degraded=true failure_stage=enqueue operation=space ids={}",
                ids,
            )
            return False

    @classmethod
    async def _enqueue_resources_async(cls, kind: str, ids: Iterable[int]) -> bool:
        members = cls._work_members(kind, ids)
        if not members:
            return True
        try:
            redis_client = await get_redis_client()
            await cls._zadd_pending_async(redis_client, members)
            await cls._schedule_pending_async(redis_client)
            return True
        except Exception:
            logger.exception(
                "Knowledge space content projection enqueue failed. degraded=true operation={} ids={}",
                kind,
                ids,
            )
            return False

    @classmethod
    async def enqueue_user_stat_async(cls, user_ids: Iterable[int]) -> bool:
        return await cls._enqueue_resources_async("user", user_ids)

    @classmethod
    async def enqueue_department_stat_async(cls, department_ids: Iterable[int]) -> bool:
        return await cls._enqueue_resources_async("department", department_ids)

    @classmethod
    async def enqueue_space_rename_stat_async(cls, space_id: int) -> bool:
        return await cls._enqueue_space_stat_async(space_id)

    @classmethod
    async def enqueue_space_delete_stat_async(cls, space_id: int) -> bool:
        return await cls._enqueue_space_stat_async(space_id)

    @classmethod
    def clear_scheduled_sync(cls) -> None:
        try:
            get_redis_client_sync().delete(cls.SCHEDULED_KEY)
        except Exception:
            logger.exception("Failed to clear knowledge space content projection schedule flag.")

    @classmethod
    def acquire_lock_sync(cls, owner_token: str | None = None) -> str | None:
        token = owner_token or generate_uuid()
        try:
            redis_client = get_redis_client_sync()
            redis_client.cluster_nodes(cls.LOCK_KEY)
            acquired = redis_client.connection.set(
                cls.LOCK_KEY,
                token,
                nx=True,
                ex=cls.LOCK_TTL_SECONDS,
            )
            return token if acquired else None
        except Exception:
            logger.exception("Failed to acquire knowledge space content projection owner lock.")
            return None

    @classmethod
    def renew_lock_sync(cls, owner_token: str) -> bool:
        try:
            redis_client = get_redis_client_sync()
            redis_client.cluster_nodes(cls.LOCK_KEY)
            return bool(
                redis_client.connection.eval(
                    cls.RENEW_LOCK_SCRIPT,
                    1,
                    cls.LOCK_KEY,
                    owner_token,
                    cls.LOCK_TTL_SECONDS,
                )
            )
        except Exception:
            logger.exception("Failed to renew knowledge space content projection owner lock. owner={}", owner_token)
            return False

    @classmethod
    def release_lock_sync(cls, owner_token: str) -> bool:
        try:
            redis_client = get_redis_client_sync()
            redis_client.cluster_nodes(cls.LOCK_KEY)
            return bool(
                redis_client.connection.eval(
                    cls.RELEASE_LOCK_SCRIPT,
                    1,
                    cls.LOCK_KEY,
                    owner_token,
                )
            )
        except Exception:
            logger.exception("Failed to release knowledge space content projection owner lock. owner={}", owner_token)
            return False

    @classmethod
    def claim_pending_sync(
        cls,
        owner_token: str,
        batch_size: int = FILE_BATCH_SIZE,
        *,
        now_ms: int | None = None,
    ) -> list[ProjectionWorkItem]:
        redis_client = get_redis_client_sync()
        redis_client.cluster_nodes(cls.PENDING_KEY)
        claimed_at_ms = now_ms or cls._now_ms()
        lease_deadline_ms = claimed_at_ms + cls.PROCESSING_LEASE_SECONDS * 1000
        values = redis_client.connection.eval(
            cls.CLAIM_SCRIPT,
            4,
            cls.PENDING_KEY,
            cls.PROCESSING_KEY,
            cls.PROCESSING_META_KEY,
            cls.LOCK_KEY,
            owner_token,
            claimed_at_ms,
            lease_deadline_ms,
            min(max(int(batch_size), 1), cls.FILE_BATCH_SIZE),
        )
        result: list[ProjectionWorkItem] = []
        for index in range(0, len(values or []), 2):
            member = cls._decode_text(values[index])
            if member is None:
                continue
            result.append(ProjectionWorkItem(member=member, enqueued_at_ms=int(float(values[index + 1]))))
        return result

    @classmethod
    def renew_claims_sync(
        cls,
        owner_token: str,
        members: Iterable[str],
        *,
        now_ms: int | None = None,
    ) -> bool:
        values = [member for member in members if member]
        if not values:
            return True
        redis_client = get_redis_client_sync()
        redis_client.cluster_nodes(cls.PROCESSING_KEY)
        deadline_ms = (now_ms or cls._now_ms()) + cls.PROCESSING_LEASE_SECONDS * 1000
        renewed = redis_client.connection.eval(
            cls.RENEW_CLAIMS_SCRIPT,
            2,
            cls.PROCESSING_KEY,
            cls.LOCK_KEY,
            owner_token,
            deadline_ms,
            *values,
        )
        return int(renewed or 0) == len(values)

    @classmethod
    def ack_claimed_sync(cls, owner_token: str, members: Iterable[str]) -> bool:
        values = [member for member in members if member]
        if not values:
            return True
        redis_client = get_redis_client_sync()
        redis_client.cluster_nodes(cls.PROCESSING_KEY)
        removed = redis_client.connection.eval(
            cls.ACK_SCRIPT,
            3,
            cls.PROCESSING_KEY,
            cls.PROCESSING_META_KEY,
            cls.LOCK_KEY,
            owner_token,
            *values,
        )
        return int(removed or 0) == len(values)

    @classmethod
    def reclaim_expired_sync(cls, *, now_ms: int | None = None) -> int:
        redis_client = get_redis_client_sync()
        redis_client.cluster_nodes(cls.PENDING_KEY)
        reclaimed = redis_client.connection.eval(
            cls.RECLAIM_SCRIPT,
            3,
            cls.PENDING_KEY,
            cls.PROCESSING_KEY,
            cls.PROCESSING_META_KEY,
            now_ms or cls._now_ms(),
        )
        return int(reclaimed or 0)

    @classmethod
    def clear_event_scheduled_sync(cls) -> None:
        try:
            get_redis_client_sync().delete(cls.EVENT_SCHEDULED_KEY)
        except Exception:
            logger.exception("Failed to clear knowledge space content event schedule flag.")

    @classmethod
    def claim_event_pending_sync(
        cls,
        owner_token: str,
        batch_size: int = FILE_BATCH_SIZE,
    ) -> list[str]:
        redis_client = get_redis_client_sync()
        redis_client.cluster_nodes(cls.EVENT_PENDING_KEY)
        now_ms = cls._now_ms()
        values = redis_client.connection.eval(
            cls.CLAIM_SCRIPT,
            4,
            cls.EVENT_PENDING_KEY,
            cls.EVENT_PROCESSING_KEY,
            cls.EVENT_PROCESSING_META_KEY,
            cls.LOCK_KEY,
            owner_token,
            now_ms,
            now_ms + cls.PROCESSING_LEASE_SECONDS * 1000,
            min(max(int(batch_size), 1), cls.FILE_BATCH_SIZE),
        )
        return [
            event_id
            for index in range(0, len(values or []), 2)
            if (event_id := cls._decode_text(values[index])) is not None
        ]

    @classmethod
    def get_event_payload_sync(cls, event_id: str) -> ContentStatEventEnvelope | None:
        redis_client = get_redis_client_sync()
        redis_client.cluster_nodes(cls.EVENT_PAYLOAD_KEY)
        payload = redis_client.connection.hget(cls.EVENT_PAYLOAD_KEY, event_id)
        if payload is None:
            return None
        return ContentStatEventEnvelope.model_validate_json(cls._decode_text(payload))

    @classmethod
    def renew_event_claims_sync(
        cls,
        owner_token: str,
        event_ids: Iterable[str],
        *,
        now_ms: int | None = None,
    ) -> bool:
        values = [event_id for event_id in event_ids if event_id]
        if not values:
            return True
        redis_client = get_redis_client_sync()
        redis_client.cluster_nodes(cls.EVENT_PROCESSING_KEY)
        deadline_ms = (now_ms or cls._now_ms()) + cls.PROCESSING_LEASE_SECONDS * 1000
        renewed = redis_client.connection.eval(
            cls.RENEW_CLAIMS_SCRIPT,
            2,
            cls.EVENT_PROCESSING_KEY,
            cls.LOCK_KEY,
            owner_token,
            deadline_ms,
            *values,
        )
        return int(renewed or 0) == len(values)

    @classmethod
    def ack_event_claimed_sync(cls, owner_token: str, event_ids: Iterable[str]) -> bool:
        values = [event_id for event_id in event_ids if event_id]
        if not values:
            return True
        redis_client = get_redis_client_sync()
        redis_client.cluster_nodes(cls.EVENT_PROCESSING_KEY)
        removed = redis_client.connection.eval(
            cls.ACK_EVENT_SCRIPT,
            4,
            cls.EVENT_PROCESSING_KEY,
            cls.EVENT_PROCESSING_META_KEY,
            cls.EVENT_PAYLOAD_KEY,
            cls.LOCK_KEY,
            owner_token,
            *values,
        )
        return int(removed or 0) == len(values)

    @classmethod
    def reclaim_expired_events_sync(cls, *, now_ms: int | None = None) -> int:
        redis_client = get_redis_client_sync()
        redis_client.cluster_nodes(cls.EVENT_PENDING_KEY)
        reclaimed = redis_client.connection.eval(
            cls.RECLAIM_SCRIPT,
            3,
            cls.EVENT_PENDING_KEY,
            cls.EVENT_PROCESSING_KEY,
            cls.EVENT_PROCESSING_META_KEY,
            now_ms or cls._now_ms(),
        )
        return int(reclaimed or 0)

    @classmethod
    def has_event_pending_sync(cls) -> bool:
        try:
            redis_client = get_redis_client_sync()
            redis_client.cluster_nodes(cls.EVENT_PENDING_KEY)
            return int(redis_client.connection.zcard(cls.EVENT_PENDING_KEY) or 0) > 0
        except Exception:
            logger.exception("Failed to inspect knowledge space content event queue.")
            return False

    @classmethod
    def event_queue_status_sync(cls) -> dict[str, int]:
        redis_client = get_redis_client_sync()
        redis_client.cluster_nodes(cls.EVENT_PENDING_KEY)
        pending_count = int(redis_client.connection.zcard(cls.EVENT_PENDING_KEY) or 0)
        processing_count = int(redis_client.connection.zcard(cls.EVENT_PROCESSING_KEY) or 0)
        oldest_rows = redis_client.connection.zrange(
            cls.EVENT_PENDING_KEY,
            0,
            0,
            withscores=True,
        )
        oldest_pending_age_ms = 0
        if oldest_rows:
            oldest_pending_age_ms = max(
                0,
                cls._now_ms() - int(float(oldest_rows[0][1])),
            )
        return {
            "event_pending_count": pending_count,
            "event_processing_count": processing_count,
            "event_oldest_pending_age_ms": oldest_pending_age_ms,
        }

    @classmethod
    def schedule_event_pending_sync_now(cls, *, countdown: int = 0) -> None:
        from bisheng.worker.telemetry.mid_table import sync_pending_knowledge_space_content_events

        sync_pending_knowledge_space_content_events.apply_async(countdown=max(int(countdown), 0))

    @classmethod
    def get_replay_floor_sync(cls) -> int:
        value = get_redis_client_sync().get(cls.REPLAY_FLOOR_KEY)
        return int(cls._decode_text(value) or 0)

    @classmethod
    def set_replay_floor_sync(cls, timestamp: int) -> None:
        get_redis_client_sync().set(
            cls.REPLAY_FLOOR_KEY,
            int(timestamp),
            expiration=None,
        )

    def upsert_event_daily_sync(
        self,
        envelope: ContentStatEventEnvelope,
        absolute_count: int,
    ) -> None:
        metric_field = {
            "preview_daily": "preview_count",
            "download_daily": "download_count",
            "favorite_daily": "favorite_count",
        }[envelope.record_type]
        local_day = datetime.strptime(envelope.local_date, "%Y-%m-%d").date()
        day_start = datetime.combine(local_day, datetime.min.time(), tzinfo=CHINA_STANDARD_TIME)
        upsert = {
            **envelope.dimensions,
            "record_type": envelope.record_type,
            "local_date": envelope.local_date,
            "timestamp": int(day_start.timestamp()),
            metric_field: int(absolute_count),
        }
        self.ensure_index_exists_sync()
        self._es_client_sync.update(
            index=self.INDEX_NAME,
            id=envelope.daily_id,
            retry_on_conflict=5,
            script={
                "lang": "painless",
                "source": (
                    f"if (ctx._source.{metric_field} == null || "
                    f"ctx._source.{metric_field} < params.count) "
                    f"{{ ctx._source.{metric_field} = params.count; }}"
                ),
                "params": {"count": int(absolute_count)},
            },
            upsert=upsert,
        )

    @classmethod
    def has_pending_sync(cls) -> bool:
        try:
            redis_client = get_redis_client_sync()
            redis_client.cluster_nodes(cls.PENDING_KEY)
            return int(redis_client.connection.zcard(cls.PENDING_KEY) or 0) > 0
        except Exception:
            logger.exception("Failed to inspect knowledge space content projection pending queue.")
            return False

    @classmethod
    def queue_status_sync(cls, *, now_ms: int | None = None) -> dict[str, int]:
        redis_client = get_redis_client_sync()
        redis_client.cluster_nodes(cls.PENDING_KEY)
        pending_count = int(redis_client.connection.zcard(cls.PENDING_KEY) or 0)
        processing_count = int(redis_client.connection.zcard(cls.PROCESSING_KEY) or 0)
        oldest = redis_client.connection.zrange(cls.PENDING_KEY, 0, 0, withscores=True)
        current_ms = now_ms or cls._now_ms()
        oldest_pending_age_ms = max(0, current_ms - int(oldest[0][1])) if oldest else 0
        return {
            "pending_count": pending_count,
            "processing_count": processing_count,
            "oldest_pending_age_ms": oldest_pending_age_ms,
        }

    @classmethod
    def schedule_pending_sync_now(cls) -> None:
        try:
            cls._schedule_pending_sync(countdown=0)
        except Exception:
            logger.exception("Failed to reschedule knowledge space content projection sync.")

    @staticmethod
    def build_file_record(
        *,
        file_record: KnowledgeFile,
        space: Knowledge,
        uploader=None,
        space_level: str | None = None,
        uploader_organization: OrganizationNameSnapshot | None = None,
        belonging_organization: OrganizationNameSnapshot | None = None,
        original_upload_organization: OrganizationNameSnapshot | None = None,
        file_category_labels: dict[str, str] | None = None,
        file_subcategory_labels: dict[str, str] | None = None,
        sync_run_id: str | None = None,
    ) -> KnowledgeSpaceContentRecord:
        uploader_user_id = int(file_record.user_id or 0)
        uploader_user_name = file_record.user_name or (uploader.user_name if uploader else str(uploader_user_id or ""))
        uploader_organization = uploader_organization or OrganizationNameSnapshot()
        belonging_organization = belonging_organization or OrganizationNameSnapshot()
        original_upload_organization = original_upload_organization or OrganizationNameSnapshot()
        normalized_space_level = str(getattr(space_level, "value", space_level) or "unknown").strip().lower()
        if normalized_space_level not in SPACE_LEVEL_LABELS:
            normalized_space_level = "unknown"

        file_category_code = get_file_category_code_from_file(file_record)
        file_subcategory_code = normalize_file_category_code(getattr(file_record, "file_subcategory_code", None))
        business_domain_code = get_business_domain_code_from_file(file_record)
        file_category_labels = file_category_labels or {}
        file_subcategory_labels = file_subcategory_labels or {}

        return KnowledgeSpaceContentRecord(
            es_id=str(file_record.id),
            record_type="file",
            sync_run_id=sync_run_id,
            timestamp=int((file_record.create_time or datetime.now()).timestamp()),
            space_id=int(space.id),
            space_name=space.name,
            space_level=normalized_space_level,
            space_level_name=SPACE_LEVEL_LABELS[normalized_space_level],
            file_id=int(file_record.id),
            file_name=file_record.file_name,
            file_type=int(file_record.file_type),
            file_category_code=file_category_code,
            file_category_name=file_category_labels.get(file_category_code, file_category_code),
            file_subcategory_code=file_subcategory_code,
            file_subcategory_name=file_subcategory_labels.get(file_subcategory_code, file_subcategory_code),
            business_domain_code=business_domain_code,
            business_domain_name=BUSINESS_DOMAIN_OPTIONS.get(business_domain_code, business_domain_code),
            projection_updated_at=int(datetime.now().timestamp()),
            uploader_user_id=uploader_user_id,
            uploader_user_name=uploader_user_name,
            **uploader_organization.prefixed("uploader"),
            **belonging_organization.prefixed("belonging"),
            **original_upload_organization.prefixed("original_upload"),
        )

    @classmethod
    async def log_preview_success(
        cls,
        *,
        file_record: KnowledgeFile,
        space: Knowledge,
        viewer_user_id: int,
        viewer_user_name: str,
        occurred_at: datetime | None = None,
    ) -> None:
        if getattr(space, "is_favorite", False):
            return
        del viewer_user_name
        await cls.enqueue_success_event_async(
            file_id=int(file_record.id),
            user_id=int(viewer_user_id),
            event_type="portal_document_read",
            record_type="preview_daily",
            source_app="bisheng_my_knowledge",
            scene="document_preview",
            entry_point="my_knowledge_preview",
            occurred_at=occurred_at,
        )

    @classmethod
    def build_download_daily_record(
        cls,
        *,
        file_record: KnowledgeSpaceContentRecord,
        local_date: str,
        download_count: int,
        sync_run_id: str,
    ) -> KnowledgeSpaceDownloadDailyRecord:
        local_day = datetime.strptime(local_date, "%Y-%m-%d").date()
        day_start = datetime.combine(local_day, datetime.min.time(), tzinfo=CHINA_STANDARD_TIME)
        dimensions = {field: getattr(file_record, field) for field in cls.PREVIEW_DIMENSION_FIELDS}
        return KnowledgeSpaceDownloadDailyRecord(
            es_id=build_daily_document_id(
                record_type="download_daily",
                file_id=file_record.file_id,
                local_date=local_date,
                dimensions=dimensions,
            ),
            record_type="download_daily",
            sync_run_id=sync_run_id,
            timestamp=int(day_start.timestamp()),
            local_date=local_date,
            download_count=download_count,
            **dimensions,
        )

    def delete_file_records_sync(self, file_ids: Iterable[int]) -> int:
        ids = self._normalize_ids(file_ids)
        if not ids:
            return 0
        self.ensure_index_exists_sync()
        actions = [
            {
                "_op_type": "delete",
                "_index": self._index_name,
                "_id": str(file_id),
            }
            for file_id in ids
        ]
        success, errors = helpers.bulk(self._es_client_sync, actions, raise_on_error=False)
        real_errors = [error for error in errors if error.get("delete", {}).get("status") != 404]
        if real_errors:
            raise RuntimeError(f"Failed to delete {len(real_errors)} knowledge space content file telemetry records.")
        return int(success or 0)

    def delete_space_records_sync(self, space_ids: Iterable[int]) -> int:
        ids = self._normalize_ids(space_ids)
        if not ids:
            return 0
        result = self.delete_by_query_sync(
            {"terms": {"space_id": ids}},
            refresh=False,
        )
        return int(result.get("deleted", 0) or 0)

    def delete_stale_file_records_sync(self, sync_run_id: str) -> int:
        self.ensure_index_exists_sync()
        self._es_client_sync.indices.refresh(index=self._index_name)
        result = self.delete_by_query_sync(
            {
                "bool": {
                    "filter": [{"term": {"record_type": "file"}}],
                    "must_not": [{"term": {"sync_run_id": sync_run_id}}],
                }
            },
            refresh=True,
            conflicts="proceed",
        )
        return int(result.get("deleted", 0) or 0)

    def delete_stale_download_daily_records_sync(self, sync_run_id: str) -> int:
        self.ensure_index_exists_sync()
        self._es_client_sync.indices.refresh(index=self._index_name)
        result = self.delete_by_query_sync(
            {
                "bool": {
                    "filter": [{"term": {"record_type": "download_daily"}}],
                    "must_not": [{"term": {"sync_run_id": sync_run_id}}],
                }
            },
            refresh=True,
            conflicts="proceed",
        )
        return int(result.get("deleted", 0) or 0)
