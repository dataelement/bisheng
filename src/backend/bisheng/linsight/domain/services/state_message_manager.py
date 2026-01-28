import asyncio
import pickle
from enum import Enum
from typing import List, Dict, Any, Optional

from loguru import logger
from pydantic import BaseModel, Field

from bisheng.linsight.domain.schemas.linsight_schema import UserInputEventSchema
from bisheng.common.errcode.http_error import ServerError
from bisheng.core.cache.redis_manager import get_redis_client_sync, get_redis_client
from bisheng.linsight.domain.models.linsight_execute_task import ExecuteTaskStatusEnum, LinsightExecuteTaskDao, \
    LinsightExecuteTask
from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersion, LinsightSessionVersionDao
from bisheng.utils.util import retry_async
from bisheng_langchain.linsight.event import BaseEvent


class MessageEventType(str, Enum):
    """
    Message event type enumeration
    """
    #  tasks starting
    TASK_START = "task_start"
    # Generate Tasks
    TASK_GENERATE = "task_generate"
    # Task status update
    TASK_STATUS_UPDATE = "task_status_update"
    # User input
    USER_INPUT = "user_input"
    # User input complete
    USER_INPUT_COMPLETED = "user_input_completed"
    # Task Execution Steps
    TASK_EXECUTE_STEP = "task_execute_step"
    # Mission-End
    TASK_END = "task_end"
    # Error Message
    ERROR_MESSAGE = "error_message"
    # Final Result
    FINAL_RESULT = "final_result"
    # Mission terminated
    TASK_TERMINATED = "task_terminated"


class MessageData(BaseModel):
    """Message Data Model"""
    event_type: MessageEventType
    data: Dict[str, Any]
    timestamp: Optional[float] = Field(default_factory=lambda: asyncio.get_event_loop().time())


class LinsightStateMessageManager:
    """Idea State and Message Manager"""

    # Class Constant
    DEFAULT_EXPIRATION = 3600
    DEFAULT_RETRY_ATTEMPTS = 3
    DEFAULT_RETRY_DELAY = 1
    KEY_PREFIX = "linsight_tasks:"

    def __init__(self, session_version_id: str):
        """
        Initializing the Inspiration State and Message Manager

        Args:
            session_version_id: Session VersionID
        """
        self._session_version_id = session_version_id
        self._redis_client = get_redis_client_sync()
        self._logger = logger

        # Redis keyManaging
        self._key_prefix = f"{self.KEY_PREFIX}{session_version_id}:"
        self._keys = {
            'session_version_info': f"{self._key_prefix}session_version_info",
            'messages': f"{self._key_prefix}messages",
            'execution_tasks': f"{self._key_prefix}execution_tasks:"
        }

    async def _handle_redis_operation(self, operation, *args, **kwargs):
        """
        ImpuestoRedisOperation error handling

        Args:
            operation: RedisAction Function
            *args: Position JSON
            **kwargs: Keyword Parameters

        Returns:
            Operating result

        Raises:
            Exception: RedisException thrown when operation failed
        """
        try:
            return await operation(*args, **kwargs)
        except Exception as e:
            self._logger.error(f"Redis operation failed: {e}")
            raise

    @retry_async(num_retries=DEFAULT_RETRY_ATTEMPTS, delay=DEFAULT_RETRY_DELAY)
    async def push_message(self, message: MessageData) -> None:
        """
        Push messages toRedisin the list

        Args:
            message: Message Model
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
        FROMRedisA message pops up in the list

        Returns:
            Message Model orNone
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
        Set session version information

        Args:
            session_version_model: Session Version Model
        """
        # Using Transactions to Ensure Data Consistency
        async with self._redis_client.async_pipeline() as pipe:
            try:
                # Write database first
                await LinsightSessionVersionDao.insert_one(session_version_model)

                # Write AgainRedis
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
        Get session version information

        Returns:
            Session Version Information Model orNone
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
        Set Execution Information

        Args:
            tasks: Execute Task List
        """
        if not tasks:
            self._logger.warning("No tasks provided to set_execution_tasks")
            return

        try:
            # Batch WriteRedis
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
        Update Execution Status

        Args:
            task_id: TaskID
            status: New status
            **kwargs: Other update fields

        Returns:
            Updated task data
        """
        try:
            # Update database first
            task_model = await LinsightExecuteTaskDao.update_by_id(
                task_id,
                status=status,
                **kwargs
            )

            # Update againRedis
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
    async def set_user_input(self, task_id: str, user_input: str, files: List[Dict[str, str]] = None) -> None:
        """
        Set User Input

        Args:
            task_id: TaskID
            user_input: User input
            files: Related Documents List
        """
        task_key = f"{self._keys['execution_tasks']}{task_id}"

        try:

            task_model = await self.get_execution_task(task_id)

            if not task_model:
                raise ValueError(f"Task with ID {task_id} not found in Redis or database.")

            user_input_event = task_model.history[-1] if task_model.history else None
            if user_input_event is None or user_input_event.get("step_type") != "call_user_input":
                raise ValueError(f"Task with ID {task_id} does not support user input.")

            user_input_event = UserInputEventSchema.model_validate(user_input_event)

            user_input_event.user_input = user_input
            user_input_event.files = files
            user_input_event.is_completed = True
            task_model.history[-1] = user_input_event.model_dump()

            task_model.status = ExecuteTaskStatusEnum.USER_INPUT_COMPLETED

            # Using Transactions to Ensure Data Consistency
            async with self._redis_client.async_pipeline() as pipe:
                await pipe.set(task_key, pickle.dumps(task_model.model_dump()), ex=self.DEFAULT_EXPIRATION)
                await pipe.execute()

            # Database updating
            await LinsightExecuteTaskDao.update_by_id(
                task_id,
                status=ExecuteTaskStatusEnum.USER_INPUT_COMPLETED,
                history=task_model.history
            )

            self._logger.info(f"Set user input for task {task_id}")

        except Exception as e:
            self._logger.error(f"Failed to set user input for task {task_id}: {e}")
            raise ServerError.http_exception()

    @retry_async(num_retries=DEFAULT_RETRY_ATTEMPTS, delay=DEFAULT_RETRY_DELAY)
    async def get_execution_task(self, task_id: str) -> Optional[LinsightExecuteTask]:
        """
        Get task execution information

        Args:
            task_id: TaskID

        Returns:
            Execute Task Model orNone
        """
        task_key = f"{self._keys['execution_tasks']}{task_id}"

        try:
            task_data = await self._redis_client.aget(task_key)

            if task_data:
                return LinsightExecuteTask.model_validate(task_data)

            # Automatically close purchase order afterRedisNo data in, fetching from database
            task_model = await LinsightExecuteTaskDao.get_by_id(task_id)
            await self.set_execution_tasks([task_model])
            return task_model

        except Exception as e:
            self._logger.error(f"Failed to get execution task {task_id}: {e}")
            return None

    @retry_async(num_retries=DEFAULT_RETRY_ATTEMPTS, delay=DEFAULT_RETRY_DELAY)
    async def add_execution_task_step(self, task_id: str, step: BaseEvent) -> None:
        """
        Add Execute Task Step

        Args:
            task_id: TaskID
            step: Execution Steps
        """
        task_key = f"{self._keys['execution_tasks']}{task_id}"

        try:
            task_data = await self.get_execution_task(task_id)

            if not task_data:
                raise ValueError(f"Task with ID {task_id} not found in Redis.")

            task_model = LinsightExecuteTask.model_validate(task_data)

            # Initialization History
            if task_model.history is None:
                task_model.history = []

            # Adding new Steps
            task_model.history.append(step.model_dump())

            # Update Redis and database
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
        Get All Execute Tasks

        Returns:
            Execute Task List
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
        Cleanup Session RelatedRedisDATA
        """
        try:
            pattern = f"{self._key_prefix}*"
            keys = await self._redis_client.akeys(pattern)

            if keys:
                await self._redis_client.adelete(*keys)
                self._logger.info(f"Cleaned up {len(keys)} keys for session {self._session_version_id}")

        except Exception as e:
            self._logger.error(f"Failed to cleanup session data: {e}")
            raise

    async def get_session_stats(self) -> Dict[str, Any]:
        """
        Get session statistics

        Returns:
            Dictionary containing session statistics
        """
        try:
            stats = {
                'session_version_id': self._session_version_id,
                'message_count': await self._redis_client.allen(self._keys['messages']),
                'has_session_info': await self._redis_client.exists(self._keys['session_version_info']),
                'task_count': 0
            }

            # Calculate number of tasks
            pattern = f"{self._keys['execution_tasks']}*"
            task_keys = await self._redis_client.akeys(pattern)
            stats['task_count'] = len(task_keys)

            return stats

        except Exception as e:
            self._logger.error(f"Failed to get session stats: {e}")
            return {'error': str(e)}

    # Clean up all session-relatedRedisDATA
    @classmethod
    async def cleanup_all_sessions(cls) -> None:
        """
        Clean up all session-relatedRedisDATA
        """
        try:
            redis_client = await get_redis_client()
            pattern = f"{cls.KEY_PREFIX}*"
            keys = await redis_client.async_connection.keys(pattern)

            if keys:
                await redis_client.async_connection.delete(*keys)
                logger.info(f"Cleaned up {len(keys)} keys for all sessions")
        except Exception as e:
            logger.error(f"Failed to cleanup all session data: {e}")
            return
