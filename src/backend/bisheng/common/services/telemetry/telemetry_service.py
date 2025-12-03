import asyncio
import logging
from asyncio import Semaphore
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from elasticsearch import AsyncElasticsearch, Elasticsearch, exceptions as es_exceptions

from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum
from bisheng.common.schemas.telemetry.base_telemetry_schema import T_EventData, BaseTelemetryEvent, UserContext, \
    UserGroupInfo, UserRoleInfo
from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.core.search.elasticsearch.manager import get_statistics_es_connection, get_statistics_es_connection_sync
from bisheng.user.domain.models.user import User
from bisheng.user.domain.repositories.implementations.user_repository_impl import UserRepositoryImpl

logger = logging.getLogger(__name__)

INDEX_MAPPING = {
    "mappings": {  # 定义索引的 Mapping
        "properties": {
            "event_id": {"type": "keyword"},
            "event_type": {"type": "keyword"},
            "trace_id": {"type": "keyword"},
            "timestamp": {"type": "date", "format": "strict_date_optional_time||epoch_millis"},
            "user_context": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer"},
                    "user_name": {"type": "keyword"},
                    "user_group_infos": {
                        "type": "object",
                        "properties": {
                            "user_group_id": {"type": "integer"},
                            "user_group_name": {"type": "keyword"}
                        }
                    },
                    "user_role_infos": {
                        "type": "object",
                        "properties": {
                            "role_id": {"type": "integer"},
                            "role_name": {"type": "keyword"}
                        }
                    }
                }
            },
            "event_data": {
                "type": "object",
                "dynamic": True
            }
        }
    }
}


class BaseTelemetryService(object):
    """Telemetry Service for logging events to Elasticsearch"""
    _index_name: str = "base_telemetry_events"
    _index_initialized: bool = False

    def __init__(self):
        self._es_client: Optional[AsyncElasticsearch] = None
        self._es_client_sync: Optional[Elasticsearch] = None

        # 线程池，用于同步方法
        self.thread_pool = ThreadPoolExecutor(max_workers=10)
        # 创建一个信号量，限制并发数量
        self._semaphore = Semaphore(10)

    async def _ensure_index(self):
        """Initialize the Elasticsearch index safely"""
        # Double-check locking pattern could be used here, but simple boolean check is "good enough" for loose consistency
        if self._index_initialized:
            return

        if not self._es_client:
            self._es_client = await get_statistics_es_connection()

        try:
            exists = await self._es_client.indices.exists(index=self._index_name)
            if not exists:
                # 传入 body 应用 Mapping
                await self._es_client.indices.create(index=self._index_name, body=INDEX_MAPPING)
        except es_exceptions.RequestError as e:
            # 并发创建时忽略 "resource_already_exists_exception"
            if "resource_already_exists_exception" not in str(e):
                logger.error(f"Failed to create ES index: {e}")
                raise e
        except Exception as e:
            logger.error(f"ES Index check failed: {e}")

        self._index_initialized = True

    def _ensure_index_sync(self):
        if self._index_initialized:
            return

        if not self._es_client_sync:
            self._es_client_sync = get_statistics_es_connection_sync()

        try:
            exists = self._es_client_sync.indices.exists(index=self._index_name)
            if not exists:
                # 传入 body
                self._es_client_sync.indices.create(index=self._index_name, body=INDEX_MAPPING)
        except es_exceptions.RequestError as e:
            if "resource_already_exists_exception" not in str(e):
                logger.error(f"Failed to create ES index sync: {e}")

        self._index_initialized = True

    @staticmethod
    async def _init_user_context(user_id: int) -> UserContext:
        async with get_async_db_session() as session:
            user_repository = UserRepositoryImpl(session)
            user = await user_repository.get_user_with_groups_and_roles_by_user_id(user_id)

        if not user:
            user = User(
                user_id=user_id,
                user_name=str(user_id)
            )

        if user.groups is None:
            user.groups = []
        if user.roles is None:
            user.roles = []

        user_context = UserContext(
            user_id=user.user_id,
            user_name=user.user_name,
            user_group_infos=[
                UserGroupInfo(
                    user_group_id=group.id,
                    user_group_name=group.group_name
                ) for group in user.groups
            ],
            user_role_infos=[
                UserRoleInfo(
                    role_id=role.id,
                    role_name=role.role_name
                ) for role in user.roles
            ]
        )
        return user_context

    @staticmethod
    def _init_user_context_sync(user_id: int) -> UserContext:
        with get_sync_db_session() as session:
            user_repository = UserRepositoryImpl(session)
            user = user_repository.get_user_with_groups_and_roles_by_user_id_sync(user_id)

        if not user:
            user = User(
                user_id=user_id,
                user_name=str(user_id)
            )

        if user.groups is None:
            user.groups = []
        if user.roles is None:
            user.roles = []

        user_context = UserContext(
            user_id=user.user_id,
            user_name=user.user_name,
            user_group_infos=[
                UserGroupInfo(
                    user_group_id=group.id,
                    user_group_name=group.group_name
                ) for group in user.groups
            ],
            user_role_infos=[
                UserRoleInfo(
                    role_id=role.id,
                    role_name=role.role_name
                ) for role in user.roles
            ]
        )
        return user_context

    @property
    def index_name(self) -> str:
        return self._index_name

    # record event task
    async def _record_event_task(self, user_id: int, event_type: BaseTelemetryTypeEnum, trace_id: str,
                                 event_data: T_EventData = None):

        # 获取信号量
        async with self._semaphore:
            try:
                logger.debug(f"Recording telemetry event for user_id {user_id}, event_type {event_type}")
                # 获取用户信息 (带异常捕获)
                user_context = await self._init_user_context(user_id)
                if not user_context:
                    # 即使查不到用户，建议也记录日志，但 user_context 为空或默认值
                    logger.warning(f"User context missing for user_id {user_id}, logging anonymously")
                    # 可以根据需求决定是否 return，或者构建一个空的 Context

                # 构建 Event
                event_info = BaseTelemetryEvent(
                    event_type=event_type,
                    user_context=user_context,  # 允许为 None 或需调整 Schema 允许 Optional
                    trace_id=trace_id,
                    event_data=event_data
                )

                # 发送 (Fire and Forget)
                await self._es_client.index(index=self.index_name, document=event_info.model_dump())

            except Exception as e:
                logger.error(f"Error in record_event_task: {e}", exc_info=True)

    async def log_event(self, user_id: int, event_type: BaseTelemetryTypeEnum, trace_id: str,
                        event_data: T_EventData = None):
        """异步记录事件到 Elasticsearch (Safe Version)"""
        try:
            # 确保 ES 连接
            if not self._es_client:
                self._es_client = await get_statistics_es_connection()

            # 确保索引存在 (Lazy Init)
            if not self._index_initialized:
                await self._ensure_index()

            # 异步记录事件
            asyncio.create_task(
                self._record_event_task(
                    user_id=user_id,
                    event_type=event_type,
                    trace_id=trace_id,
                    event_data=event_data
                )
            )

        except Exception as e:
            # 吞掉异常，不要让日志系统搞崩主业务
            logger.error(f"Failed to log telemetry event: {e}", exc_info=True)

    # record event task thread sync
    def _record_event_task_sync(self, user_id: int, event_type: BaseTelemetryTypeEnum, trace_id: str,
                                event_data: T_EventData = None):
        try:
            logger.debug(f"Recording telemetry event sync for user_id {user_id}, event_type {event_type}")
            user_context = self._init_user_context_sync(user_id)

            event_info = BaseTelemetryEvent(
                event_type=event_type,
                user_context=user_context,
                trace_id=trace_id,
                event_data=event_data
            )
            self._es_client_sync.index(index=self.index_name, document=event_info.model_dump())
        except Exception as e:
            logger.error(f"Failed to log telemetry event sync in thread: {e}", exc_info=True)

    def log_event_sync(self, user_id: int, event_type: BaseTelemetryTypeEnum, trace_id: str,
                       event_data: T_EventData = None):
        """同步记录事件到 Elasticsearch (Safe Version)"""
        try:
            if not self._es_client_sync:
                self._es_client_sync = get_statistics_es_connection_sync()

            if not self._index_initialized:
                self._ensure_index_sync()

            # 使用线程池执行同步任务
            self.thread_pool.submit(
                self._record_event_task_sync,
                user_id,
                event_type,
                trace_id,
                event_data
            )
        except Exception as e:
            logger.error(f"Failed to log telemetry event sync: {e}", exc_info=True)


telemetry_service = BaseTelemetryService()
