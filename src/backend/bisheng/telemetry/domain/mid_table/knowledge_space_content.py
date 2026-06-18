from collections.abc import Iterable
from datetime import datetime
from typing import Any, ClassVar

from elasticsearch import helpers
from loguru import logger
from pydantic import Field

from bisheng.common.schemas.telemetry.base_telemetry_schema import UserDepartmentInfo, UserGroupInfo, UserRoleInfo
from bisheng.core.cache.redis_manager import get_redis_client, get_redis_client_sync
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.telemetry.domain.mid_table.base import BaseMidTable, BaseRecord
from bisheng.user.domain.repositories.implementations.user_repository_impl import UserRepositoryImpl
from bisheng.utils import generate_uuid


class KnowledgeSpaceContentRecord(BaseRecord):
    record_type: str
    sync_run_id: str | None = None

    space_id: int
    space_name: str
    file_id: int
    file_name: str
    file_type: int

    uploader_user_id: int
    uploader_user_name: str
    uploader_department_infos: list[UserDepartmentInfo] = Field(default_factory=list)

    event_id: str | None = None
    viewer_user_id: int | None = None
    viewer_user_name: str | None = None
    action_result: str | None = None


class KnowledgeSpaceContentStat(BaseMidTable):
    _index_name: str = "mid_knowledge_space_content_stat"
    FILE_PENDING_KEY: ClassVar[str] = "telemetry:knowledge_space_content:file_pending"
    SPACE_RENAME_PENDING_KEY: ClassVar[str] = "telemetry:knowledge_space_content:space_rename_pending"
    SPACE_DELETE_PENDING_KEY: ClassVar[str] = "telemetry:knowledge_space_content:space_delete_pending"
    SCHEDULED_KEY: ClassVar[str] = "telemetry:knowledge_space_content:scheduled"
    LOCK_KEY: ClassVar[str] = "telemetry:knowledge_space_content:lock"
    SCHEDULE_DELAY_SECONDS: ClassVar[int] = 5
    SCHEDULE_TTL_SECONDS: ClassVar[int] = 10
    LOCK_TTL_SECONDS: ClassVar[int] = 60
    FILE_BATCH_SIZE: ClassVar[int] = 500
    _mappings: dict[str, Any] = {
        "record_type": {"type": "keyword"},
        "sync_run_id": {"type": "keyword"},
        "space_id": {"type": "keyword", "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}}},
        "space_name": {"type": "keyword", "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}}},
        "file_id": {"type": "keyword", "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}}},
        "file_name": {"type": "keyword", "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}}},
        "file_type": {"type": "integer"},
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
                "department_id": {
                    "type": "keyword",
                    "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}},
                },
                "department_name": {
                    "type": "keyword",
                    "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}},
                },
            },
        },
        "event_id": {"type": "keyword"},
        "viewer_user_id": {"type": "keyword"},
        "viewer_user_name": {"type": "keyword"},
        "action_result": {"type": "keyword"},
    }

    @staticmethod
    def _normalize_ids(ids: Iterable[int]) -> list[int]:
        normalized: list[int] = []
        seen = set()
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

    @classmethod
    def _sadd_sync(cls, redis_client, key: str, ids: Iterable[int]) -> None:
        values = [str(item_id) for item_id in cls._normalize_ids(ids)]
        if not values:
            return
        redis_client.cluster_nodes(key)
        redis_client.connection.sadd(key, *values)

    @classmethod
    async def _sadd_async(cls, redis_client, key: str, ids: Iterable[int]) -> None:
        values = [str(item_id) for item_id in cls._normalize_ids(ids)]
        if not values:
            return
        await redis_client.acluster_nodes(key)
        await redis_client.async_connection.sadd(key, *values)

    @staticmethod
    def _decode_redis_member(value) -> int | None:
        if value is None:
            return None
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _spop_ids_sync(cls, redis_client, key: str, count: int | None = None) -> list[int]:
        redis_client.cluster_nodes(key)
        if count is None:
            raw_values = redis_client.connection.spop(key)
        else:
            raw_values = redis_client.connection.spop(key, count)
        if raw_values is None:
            return []
        if isinstance(raw_values, (bytes, str, int)):
            raw_values = [raw_values]
        ids = []
        for raw_value in raw_values:
            item_id = cls._decode_redis_member(raw_value)
            if item_id is not None:
                ids.append(item_id)
        return ids

    @classmethod
    def _scard_sync(cls, redis_client, key: str) -> int:
        redis_client.cluster_nodes(key)
        return int(redis_client.connection.scard(key) or 0)

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
    def enqueue_file_stat_sync(cls, file_ids: Iterable[int]) -> None:
        ids = cls._normalize_ids(file_ids)
        if not ids:
            return
        try:
            redis_client = get_redis_client_sync()
            cls._sadd_sync(redis_client, cls.FILE_PENDING_KEY, ids)
            cls._schedule_pending_sync(redis_client)
        except Exception:
            logger.exception("Failed to enqueue knowledge space content file telemetry sync.")

    @classmethod
    async def enqueue_file_stat_async(cls, file_ids: Iterable[int]) -> None:
        ids = cls._normalize_ids(file_ids)
        if not ids:
            return
        try:
            redis_client = await get_redis_client()
            await cls._sadd_async(redis_client, cls.FILE_PENDING_KEY, ids)
            await cls._schedule_pending_async(redis_client)
        except Exception:
            logger.exception("Failed to enqueue knowledge space content file telemetry sync.")

    @classmethod
    async def enqueue_space_rename_stat_async(cls, space_id: int) -> None:
        ids = cls._normalize_ids([space_id])
        if not ids:
            return
        try:
            redis_client = await get_redis_client()
            await cls._sadd_async(redis_client, cls.SPACE_RENAME_PENDING_KEY, ids)
            await cls._schedule_pending_async(redis_client)
        except Exception:
            logger.exception("Failed to enqueue knowledge space content space rename telemetry sync.")

    @classmethod
    async def enqueue_space_delete_stat_async(cls, space_id: int) -> None:
        ids = cls._normalize_ids([space_id])
        if not ids:
            return
        try:
            redis_client = await get_redis_client()
            await cls._sadd_async(redis_client, cls.SPACE_DELETE_PENDING_KEY, ids)
            await cls._schedule_pending_async(redis_client)
        except Exception:
            logger.exception("Failed to enqueue knowledge space content space delete telemetry sync.")

    @classmethod
    def pop_pending_file_ids_sync(cls, batch_size: int = FILE_BATCH_SIZE) -> list[int]:
        return cls._spop_ids_sync(get_redis_client_sync(), cls.FILE_PENDING_KEY, batch_size)

    @classmethod
    def pop_pending_space_rename_ids_sync(cls) -> list[int]:
        redis_client = get_redis_client_sync()
        count = cls._scard_sync(redis_client, cls.SPACE_RENAME_PENDING_KEY)
        return cls._spop_ids_sync(redis_client, cls.SPACE_RENAME_PENDING_KEY, count) if count else []

    @classmethod
    def pop_pending_space_delete_ids_sync(cls) -> list[int]:
        redis_client = get_redis_client_sync()
        count = cls._scard_sync(redis_client, cls.SPACE_DELETE_PENDING_KEY)
        return cls._spop_ids_sync(redis_client, cls.SPACE_DELETE_PENDING_KEY, count) if count else []

    @classmethod
    def clear_scheduled_sync(cls) -> None:
        try:
            get_redis_client_sync().delete(cls.SCHEDULED_KEY)
        except Exception:
            logger.exception("Failed to clear knowledge space content telemetry schedule flag.")

    @classmethod
    def acquire_lock_sync(cls) -> bool:
        try:
            return bool(get_redis_client_sync().setNx(cls.LOCK_KEY, 1, expiration=cls.LOCK_TTL_SECONDS))
        except Exception:
            logger.exception("Failed to acquire knowledge space content telemetry sync lock.")
            return False

    @classmethod
    def release_lock_sync(cls) -> None:
        try:
            get_redis_client_sync().delete(cls.LOCK_KEY)
        except Exception:
            logger.exception("Failed to release knowledge space content telemetry sync lock.")

    @classmethod
    def has_pending_sync(cls) -> bool:
        try:
            redis_client = get_redis_client_sync()
            return any(
                cls._scard_sync(redis_client, key) > 0
                for key in (
                    cls.FILE_PENDING_KEY,
                    cls.SPACE_RENAME_PENDING_KEY,
                    cls.SPACE_DELETE_PENDING_KEY,
                )
            )
        except Exception:
            logger.exception("Failed to inspect knowledge space content telemetry pending sets.")
            return False

    @classmethod
    def schedule_pending_sync_now(cls) -> None:
        try:
            cls._schedule_pending_sync(countdown=0)
        except Exception:
            logger.exception("Failed to reschedule knowledge space content telemetry sync.")

    @staticmethod
    def build_file_record(
        *,
        file_record: KnowledgeFile,
        space: Knowledge,
        uploader=None,
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
        return KnowledgeSpaceContentRecord(
            es_id=f"file_{file_record.id}",
            record_type="file",
            sync_run_id=sync_run_id,
            user_id=uploader_user_id,
            user_name=uploader_user_name,
            user_group_infos=[
                UserGroupInfo(user_group_id=group.id, user_group_name=group.group_name)
                for group in getattr(uploader, "groups", []) or []
            ]
            if uploader
            else [],
            user_role_infos=[
                UserRoleInfo(role_id=role.id, role_name=role.role_name, group_id=role.group_id)
                for role in getattr(uploader, "roles", []) or []
            ]
            if uploader
            else [],
            user_department_infos=uploader_departments,
            timestamp=int((file_record.create_time or datetime.now()).timestamp()),
            space_id=int(space.id),
            space_name=space.name,
            file_id=int(file_record.id),
            file_name=file_record.file_name,
            file_type=int(file_record.file_type),
            uploader_user_id=uploader_user_id,
            uploader_user_name=uploader_user_name,
            uploader_department_infos=uploader_departments,
        )

    @staticmethod
    async def _get_user_departments(user_id: int | None) -> list[UserDepartmentInfo]:
        if not user_id:
            return []
        async with get_async_db_session() as session:
            user_repository = UserRepositoryImpl(session)
            user = await user_repository.get_user_with_groups_and_roles_by_user_id(user_id)
        if not user:
            return []
        return [
            UserDepartmentInfo(department_id=dept.id, department_name=dept.name)
            for dept in getattr(user, "departments", []) or []
        ]

    @classmethod
    async def log_preview_success(
        cls,
        *,
        file_record: KnowledgeFile,
        space: Knowledge,
        viewer_user_id: int,
        viewer_user_name: str,
    ) -> None:
        event_id = generate_uuid()
        uploader_user_id = int(file_record.user_id or 0)
        uploader_user_name = file_record.user_name or str(uploader_user_id or "")
        record = KnowledgeSpaceContentRecord(
            es_id=f"preview_{event_id}",
            record_type="preview",
            timestamp=int(datetime.now().timestamp()),
            user_id=int(viewer_user_id or 0),
            user_name=viewer_user_name or str(viewer_user_id or ""),
            user_group_infos=[],
            user_role_infos=[],
            user_department_infos=[],
            space_id=int(space.id),
            space_name=space.name,
            file_id=int(file_record.id),
            file_name=file_record.file_name,
            file_type=int(file_record.file_type),
            uploader_user_id=uploader_user_id,
            uploader_user_name=uploader_user_name,
            uploader_department_infos=await cls._get_user_departments(uploader_user_id),
            event_id=event_id,
            viewer_user_id=int(viewer_user_id or 0),
            viewer_user_name=viewer_user_name or str(viewer_user_id or ""),
            action_result="success",
        )
        await cls(ensure_sync_index=False).insert_record(record)

    def delete_file_records_sync(self, file_ids: Iterable[int]) -> int:
        ids = self._normalize_ids(file_ids)
        if not ids:
            return 0
        self.ensure_index_exists_sync()
        actions = [
            {
                "_op_type": "delete",
                "_index": self._index_name,
                "_id": f"file_{file_id}",
            }
            for file_id in ids
        ]
        success, _errors = helpers.bulk(self._es_client_sync, actions, raise_on_error=False)
        return int(success or 0)

    def delete_space_file_records_sync(self, space_ids: Iterable[int]) -> int:
        ids = self._normalize_ids(space_ids)
        if not ids:
            return 0
        result = self.delete_by_query_sync(
            {
                "bool": {
                    "filter": [
                        {"term": {"record_type": "file"}},
                        {"terms": {"space_id": ids}},
                    ]
                }
            },
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
