import asyncio
import pickle
from enum import Enum
from loguru import logger
from typing import List, Dict, Any, Optional

from pydantic import BaseModel, Field

from bisheng.cache.redis import redis_client
from bisheng.database.models import LinsightExecuteTask
from bisheng.database.models.linsight_execute_task import ExecuteTaskStatusEnum, LinsightExecuteTaskDao
from bisheng.database.models.linsight_session_version import LinsightSessionVersion, LinsightSessionVersionDao
from bisheng.utils.util import retry_async
from bisheng_langchain.linsight.event import ExecStep


class MessageEventType(str, Enum):
    """
    消息事件类型枚举
    """
    # 任务开始
    TASK_START = "task_start"
    # 生成任务
    TASK_GENERATE = "task_generate"
    # 任务状态更新
    TASK_STATUS_UPDATE = "task_status_update"
    # 用户输入
    USER_INPUT = "user_input"
    # 用户输入完成
    USER_INPUT_COMPLETED = "user_input_completed"
    # 任务执行步骤
    TASK_EXECUTE_STEP = "task_execute_step"
    # 任务结束
    TASK_END = "task_end"
    # 错误消息
    ERROR_MESSAGE = "error_message"
    # 最终结果
    FINAL_RESULT = "final_result"
    # 任务终止
    TASK_TERMINATED = "task_terminated"


class MessageData(BaseModel):
    """消息数据模型"""
    event_type: MessageEventType
    data: Dict[str, Any]
    timestamp: Optional[float] = Field(default_factory=lambda: asyncio.get_event_loop().time())


class LinsightStateMessageManager:
    """灵思状态与消息管理器"""

    # 类常量
    DEFAULT_EXPIRATION = 3600
    DEFAULT_RETRY_ATTEMPTS = 3
    DEFAULT_RETRY_DELAY = 1

    def __init__(self, session_version_id: str):
        """
        初始化灵思状态与消息管理器

        Args:
            session_version_id: 会话版本ID
        """
        self._session_version_id = session_version_id
        self._redis_client = redis_client
        self._logger = logger

        # Redis key管理
        self._key_prefix = f"linsight_tasks:{self._session_version_id}:"
        self._keys = {
            'session_version_info': f"{self._key_prefix}session_version_info",
            'messages': f"{self._key_prefix}messages",
            'execution_tasks': f"{self._key_prefix}execution_tasks:"
        }

    async def _handle_redis_operation(self, operation, *args, **kwargs):
        """
        统一的Redis操作错误处理

        Args:
            operation: Redis操作函数
            *args: 位置参数
            **kwargs: 关键字参数

        Returns:
            操作结果

        Raises:
            Exception: Redis操作失败时抛出异常
        """
        try:
            return await operation(*args, **kwargs)
        except Exception as e:
            self._logger.error(f"Redis operation failed: {e}")
            raise

    @retry_async(num_retries=DEFAULT_RETRY_ATTEMPTS, delay=DEFAULT_RETRY_DELAY)
    async def push_message(self, message: MessageData) -> None:
        """
        将消息推送到Redis列表中

        Args:
            message: 消息模型
        """
        self._logger.info(f"Pushing message: {message.event_type}")

        await self._handle_redis_operation(
            self._redis_client.arpush,
            self._keys['messages'],
            message.model_dump()
        )
        self._logger.info(f"Message pushed: {message.event_type}")

    @retry_async(num_retries=DEFAULT_RETRY_ATTEMPTS, delay=DEFAULT_RETRY_DELAY)
    async def pop_message(self) -> Optional[MessageData]:
        """
        从Redis列表中弹出一条消息

        Returns:
            消息模型或None
        """
        try:

            message_data = await self._redis_client.ablpop(self._keys['messages'])

            if message_data:
                return MessageData.model_validate(message_data)
            return None

        except Exception as e:
            self._logger.error(f"Failed to pop message: {e}")
            raise e

    @retry_async(num_retries=DEFAULT_RETRY_ATTEMPTS, delay=DEFAULT_RETRY_DELAY)
    async def set_session_version_info(self, session_version_model) -> None:
        """
        设置会话版本信息

        Args:
            session_version_model: 会话版本模型
        """
        # 使用事务确保数据一致性
        async with self._redis_client.async_pipeline() as pipe:
            try:
                # 先写入数据库
                await LinsightSessionVersionDao.insert_one(session_version_model)

                # 再写入Redis
                await pipe.set(
                    self._keys['session_version_info'],
                    pickle.dumps(session_version_model.model_dump()),
                    ex=self.DEFAULT_EXPIRATION
                )
                await pipe.execute()

                self._logger.info(f"Session version info set: {self._session_version_id}")

            except Exception as e:
                self._logger.error(f"Failed to set session version info: {e}")
                raise

    @retry_async(num_retries=DEFAULT_RETRY_ATTEMPTS, delay=DEFAULT_RETRY_DELAY)
    async def get_session_version_info(self) -> Optional[LinsightSessionVersion]:
        """
        获取会话版本信息

        Returns:
            会话版本信息模型或None
        """
        try:
            info = await self._handle_redis_operation(
                self._redis_client.aget,
                self._keys['session_version_info']
            )
            if not info:
                self._logger.warning(f"No session version info found for {self._session_version_id}")
                session_version_model = await LinsightSessionVersionDao.get_by_id(self._session_version_id)
                await self.set_session_version_info(session_version_model)
                return session_version_model

            return LinsightSessionVersion.model_validate(info)
        except Exception as e:
            self._logger.error(f"Failed to get session version info: {e}")
            session_version_model = await LinsightSessionVersionDao.get_by_id(self._session_version_id)
            await self.set_session_version_info(session_version_model)
            return session_version_model

    @retry_async(num_retries=DEFAULT_RETRY_ATTEMPTS, delay=DEFAULT_RETRY_DELAY)
    async def set_execution_tasks(self, tasks: List[LinsightExecuteTask]) -> None:
        """
        设置执行任务信息

        Args:
            tasks: 执行任务列表
        """
        if not tasks:
            self._logger.warning("No tasks provided to set_execution_tasks")
            return

        try:
            # 批量写入Redis
            tasks_mapping = {
                f"{self._keys['execution_tasks']}{task.id}": task.model_dump()
                for task in tasks
            }

            await self._redis_client.amset(tasks_mapping, expiration=self.DEFAULT_EXPIRATION)


        except Exception as e:
            self._logger.error(f"Failed to set execution tasks: {e}")
            raise

    @retry_async(num_retries=DEFAULT_RETRY_ATTEMPTS, delay=DEFAULT_RETRY_DELAY)
    async def update_execution_task_status(
            self,
            task_id: str,
            status: ExecuteTaskStatusEnum,
            **kwargs
    ) -> Dict[str, Any]:
        """
        更新执行任务状态

        Args:
            task_id: 任务ID
            status: 新状态
            **kwargs: 其他更新字段

        Returns:
            更新后的任务数据
        """
        try:
            # 先更新数据库
            task_model = await LinsightExecuteTaskDao.update_by_id(
                task_id,
                status=status,
                **kwargs
            )

            # 再更新Redis
            task_key = f"{self._keys['execution_tasks']}{task_id}"
            task_data = task_model.model_dump()

            await self._redis_client.aset(
                task_key,
                task_data,
                expiration=self.DEFAULT_EXPIRATION
            )

            self._logger.info(f"Updated task {task_id} status to {status}")
            return task_data

        except Exception as e:
            self._logger.error(f"Failed to update task {task_id} status: {e}")
            raise

    @retry_async(num_retries=DEFAULT_RETRY_ATTEMPTS, delay=DEFAULT_RETRY_DELAY)
    async def set_user_input(self, task_id: str, user_input: str) -> None:
        """
        设置用户输入

        Args:
            task_id: 任务ID
            user_input: 用户输入内容
        """
        task_key = f"{self._keys['execution_tasks']}{task_id}"

        try:

            task_model = await self.get_execution_task(task_id)

            if not task_model:
                raise ValueError(f"Task with ID {task_id} not found in Redis or database.")

            task_model.user_input = user_input
            task_model.status = ExecuteTaskStatusEnum.USER_INPUT_COMPLETED

            # 使用事务确保数据一致性
            async with self._redis_client.async_pipeline() as pipe:
                await pipe.set(task_key, pickle.dumps(task_model.model_dump()), ex=self.DEFAULT_EXPIRATION)
                await pipe.execute()

            # 更新数据库
            await LinsightExecuteTaskDao.update_by_id(
                task_id,
                user_input=user_input,
                status=ExecuteTaskStatusEnum.USER_INPUT_COMPLETED
            )

            self._logger.info(f"Set user input for task {task_id}")

        except Exception as e:
            self._logger.error(f"Failed to set user input for task {task_id}: {e}")
            raise

    @retry_async(num_retries=DEFAULT_RETRY_ATTEMPTS, delay=DEFAULT_RETRY_DELAY)
    async def get_execution_task(self, task_id: str) -> Optional[LinsightExecuteTask]:
        """
        获取执行任务信息

        Args:
            task_id: 任务ID

        Returns:
            执行任务模型或None
        """
        task_key = f"{self._keys['execution_tasks']}{task_id}"

        try:
            task_data = await self._redis_client.aget(task_key)

            if task_data:
                return LinsightExecuteTask.model_validate(task_data)

            # 如果Redis中没有数据，从数据库获取
            task_model = await LinsightExecuteTaskDao.get_by_id(task_id)
            await self.set_execution_tasks([task_model])
            return task_model

        except Exception as e:
            self._logger.error(f"Failed to get execution task {task_id}: {e}")
            return None

    @retry_async(num_retries=DEFAULT_RETRY_ATTEMPTS, delay=DEFAULT_RETRY_DELAY)
    async def add_execution_task_step(self, task_id: str, step: ExecStep) -> None:
        """
        添加执行任务步骤

        Args:
            task_id: 任务ID
            step: 执行步骤
        """
        task_key = f"{self._keys['execution_tasks']}{task_id}"

        try:
            task_data = await self.get_execution_task(task_id)

            if not task_data:
                raise ValueError(f"Task with ID {task_id} not found in Redis.")

            task_model = LinsightExecuteTask.model_validate(task_data)

            # 初始化历史记录
            if task_model.history is None:
                task_model.history = []

            # 添加新步骤
            task_model.history.append(step.model_dump())

            # 更新Redis和数据库
            await self._redis_client.aset(
                task_key,
                task_model.model_dump(),
                expiration=self.DEFAULT_EXPIRATION
            )

            await LinsightExecuteTaskDao.update_by_id(
                task_id,
                history=task_model.history
            )

            self._logger.info(f"Added step to task {task_id}")

        except Exception as e:
            self._logger.error(f"Failed to add step to task {task_id}: {e}")
            raise

    async def get_execution_tasks(self):
        """
        获取所有执行任务

        Returns:
            执行任务列表
        """
        try:
            pattern = f"{self._keys['execution_tasks']}*"
            task_keys = await self._redis_client.akeys(pattern)

            if not task_keys:
                return []

            tasks_data = await self._redis_client.amget(task_keys)
            tasks = [LinsightExecuteTask.model_validate(task) for task in tasks_data if task]

            if not tasks:
                tasks = await LinsightExecuteTaskDao.get_by_session_version_id(
                    session_version_id=self._session_version_id)
            return tasks

        except Exception as e:
            self._logger.error(f"Failed to get execution tasks: {e}")
            return []

    async def cleanup_session_data(self) -> None:
        """
        清理会话相关的Redis数据
        """
        try:
            pattern = f"{self._key_prefix}*"
            keys = await self._redis_client.keys(pattern)

            if keys:
                await self._redis_client.delete(*keys)
                self._logger.info(f"Cleaned up {len(keys)} keys for session {self._session_version_id}")

        except Exception as e:
            self._logger.error(f"Failed to cleanup session data: {e}")
            raise

    async def get_session_stats(self) -> Dict[str, Any]:
        """
        获取会话统计信息

        Returns:
            包含会话统计信息的字典
        """
        try:
            stats = {
                'session_version_id': self._session_version_id,
                'message_count': await self._redis_client.llen(self._keys['messages']),
                'has_session_info': await self._redis_client.exists(self._keys['session_version_info']),
                'task_count': 0
            }

            # 计算任务数量
            pattern = f"{self._keys['execution_tasks']}*"
            task_keys = await self._redis_client.keys(pattern)
            stats['task_count'] = len(task_keys)

            return stats

        except Exception as e:
            self._logger.error(f"Failed to get session stats: {e}")
            return {'error': str(e)}
