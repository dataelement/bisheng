from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar

from elasticsearch import exceptions as es_exceptions
from elasticsearch import helpers
from loguru import logger
from pydantic import BaseModel, Field

from bisheng.common.constants.telemetry import KNOWLEDGE_SPACE_CONTENT_STAT_INDEX
from bisheng.common.schemas.telemetry.base_telemetry_schema import UserDepartmentInfo
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
    space_department_id: int | None = None
    space_department_name: str | None = None
    primary_department_id: int | None = None
    primary_department_name: str | None = None
    projection_updated_at: int | None = None
    uploader_user_id: int
    uploader_user_name: str
    uploader_department_infos: list[UserDepartmentInfo] = Field(default_factory=list)


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

    _mappings: dict[str, Any] = {
        "record_type": {"type": "keyword"},
        "sync_run_id": {"type": "keyword"},
        "timestamp": {
            "type": "date",
            "format": "strict_date_optional_time||epoch_second",
        },
        "local_date": {"type": "keyword"},
        "preview_count": {"type": "long"},
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
        "space_department_id": {"type": "keyword"},
        "space_department_name": {
            "type": "keyword",
            "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}},
        },
        "primary_department_id": {"type": "keyword"},
        "primary_department_name": {
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
        "uploader_department_infos": {
            "type": "nested",
            "properties": {
                "department_id": {"type": "keyword"},
                "department_name": {
                    "type": "keyword",
                    "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}},
                },
            },
        },
    }

    PREVIEW_DIMENSION_FIELDS: ClassVar[tuple[str, ...]] = (
        "space_id",
        "space_name",
        "space_level",
        "space_level_name",
        "file_id",
        "file_name",
        "file_type",
        "file_category_code",
        "file_category_name",
        "file_subcategory_code",
        "file_subcategory_name",
        "business_domain_code",
        "business_domain_name",
        "space_department_id",
        "space_department_name",
        "primary_department_id",
        "primary_department_name",
        "uploader_user_id",
        "uploader_user_name",
        "uploader_department_infos",
    )

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
        space_department=None,
        primary_department=None,
        file_category_labels: dict[str, str] | None = None,
        file_subcategory_labels: dict[str, str] | None = None,
        sync_run_id: str | None = None,
    ) -> KnowledgeSpaceContentRecord:
        uploader_user_id = int(file_record.user_id or 0)
        uploader_user_name = file_record.user_name or (uploader.user_name if uploader else str(uploader_user_id or ""))
        uploader_departments = (
            [
                UserDepartmentInfo(department_id=dept.id, department_name=dept.name)
                for dept in getattr(uploader, "departments", []) or []
            ]
            if uploader
            else []
        )
        if primary_department is None and uploader:
            raw_primary_department_id = getattr(uploader, "dept_id", None)
            try:
                primary_department_id = int(raw_primary_department_id or 0)
            except (TypeError, ValueError):
                primary_department_id = 0
            primary_department = next(
                (
                    department
                    for department in getattr(uploader, "departments", []) or []
                    if int(getattr(department, "id", 0) or 0) == primary_department_id
                ),
                None,
            )
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
            space_department_id=(
                int(getattr(space_department, "id", None) or getattr(space_department, "department_id", 0)) or None
            ),
            space_department_name=getattr(space_department, "name", None),
            primary_department_id=(
                int(getattr(primary_department, "id", None) or getattr(primary_department, "department_id", 0)) or None
            ),
            primary_department_name=getattr(primary_department, "name", None),
            projection_updated_at=int(datetime.now().timestamp()),
            uploader_user_id=uploader_user_id,
            uploader_user_name=uploader_user_name,
            uploader_department_infos=uploader_departments,
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
        del viewer_user_id, viewer_user_name
        file_id = int(file_record.id)
        mid_table = cls(ensure_sync_index=False)
        try:
            await mid_table.ensure_index_exists()
            snapshot = await mid_table._es_client.get(index=cls.INDEX_NAME, id=str(file_id))
            source = snapshot.get("_source") or {}
            if source.get("record_type") != "file":
                logger.error(
                    "Knowledge space preview projection skipped. index={} file_id={} failure_stage=snapshot_invalid",
                    cls.INDEX_NAME,
                    file_id,
                )
                return

            local_time = (occurred_at or datetime.now(CHINA_STANDARD_TIME)).astimezone(CHINA_STANDARD_TIME)
            local_date = local_time.date().isoformat()
            day_start = datetime.combine(local_time.date(), datetime.min.time(), tzinfo=CHINA_STANDARD_TIME)
            upsert = {field: source.get(field) for field in cls.PREVIEW_DIMENSION_FIELDS}
            upsert.update(
                {
                    "record_type": "preview_daily",
                    "local_date": local_date,
                    "timestamp": int(day_start.timestamp()),
                    "preview_count": 1,
                }
            )
            await mid_table._es_client.update(
                index=cls.INDEX_NAME,
                id=f"preview_{file_id}_{local_date}",
                retry_on_conflict=5,
                script={
                    "lang": "painless",
                    "source": "ctx._source.preview_count += params.increment",
                    "params": {"increment": 1},
                },
                upsert=upsert,
            )
        except es_exceptions.NotFoundError:
            logger.error(
                "Knowledge space preview projection skipped. index={} file_id={} failure_stage=snapshot_missing",
                cls.INDEX_NAME,
                file_id,
            )
        except Exception:
            logger.exception(
                "Knowledge space preview projection failed. index={} file_id={} failure_stage=preview_update",
                cls.INDEX_NAME,
                file_id,
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
