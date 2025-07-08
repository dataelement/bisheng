from typing import List
from uuid import UUID

from pydantic import BaseModel

from bisheng.cache.redis import redis_client
from bisheng.database.models import LinsightExecuteTask
from bisheng.database.models.linsight_execute_task import ExecuteTaskStatusEnum, LinsightExecuteTaskDao
from bisheng.database.models.linsight_session_version import SessionVersionStatusEnum, LinsightSessionVersion, \
    LinsightSessionVersionDao
from bisheng.utils.util import retry_async
from bisheng_langchain.linsight.event import ExecStep


class SessionVersionInfo(BaseModel):
    """会话版本信息模型"""
    id: UUID
    session_id: UUID
    user_id: UUID
    status: SessionVersionStatusEnum


class LinsightStateMessageManager(object):
    """灵思状态与消息管理器"""

    def __init__(self, session_version_id: UUID):
        """
        初始化灵思状态与消息管理器
        :param session_version_id: 会话版本ID
        """
        self._session_version_id = session_version_id
        self._redis_client = redis_client
        # redis key前缀
        self._key_prefix = f"linsight_tasks:{self._session_version_id.hex}:"
        # session_version_info key
        self._session_version_info_key = f"{self._key_prefix}session_version_info"
        # execution_tasks key
        self._execution_tasks_key = f"{self._key_prefix}execution_tasks:"

    # 写入session_version_info
    async def set_session_version_info(self, session_version_model):
        """
        设置会话版本信息
        :param session_version_model:
        """
        await LinsightSessionVersionDao.insert_one(session_version_model)

        await self._redis_client.aset(self._session_version_info_key,
                                      session_version_model.model_dump())

    # 获取session_version_info
    async def get_session_version_info(self) -> LinsightSessionVersion | None:
        """
        获取会话版本信息
        :return: 会话版本信息模型
        """
        info = await self._redis_client.aget(self._session_version_info_key)
        if info:
            return LinsightSessionVersion.model_validate(info)
        return None

    # 写入执行任务信息
    @retry_async(num_retries=3, delay=1)
    async def set_execution_task(self, tasks: List[LinsightExecuteTask]):
        """
        设置执行任务信息
        :param tasks: 执行任务列表
        """
        if not tasks:
            return

        # 写入到Redis
        tasks_mapping = {f"{self._execution_tasks_key}{task.id}": task.model_dump() for task in
                         tasks}

        await self._redis_client.amset(tasks_mapping, expiration=3600)

    # 修改执行任务状态
    @retry_async(num_retries=3, delay=1)
    async def update_execution_task_status(self, task_id: str, status: ExecuteTaskStatusEnum, **kwargs):
        """
        更新执行任务状态
        :param task_id: 任务ID
        :param status: 新状态
        """
        task_model = await LinsightExecuteTaskDao.update_by_id(task_id, status=status, **kwargs)

        task_key = f"{self._execution_tasks_key}{task_id}"

        task_data = task_model.model_dump()
        await self._redis_client.aset(task_key, task_data)

    # 设置用户输入
    @retry_async(num_retries=3, delay=1)
    async def set_user_input(self, task_id: str, user_input: str):
        """
        设置用户输入
        :param task_id: 任务ID
        :param user_input: 用户输入内容
        """
        task_key = f"{self._execution_tasks_key}{task_id}"
        task_data = await self._redis_client.aget(task_key)

        if not task_data:
            raise ValueError(f"Task with ID {task_id} not found in Redis.")

        task_model = LinsightExecuteTask.model_validate(task_data)
        task_model.user_input = user_input
        task_model.status = ExecuteTaskStatusEnum.USER_INPUT_COMPLETED

        # 更新任务数据
        await self._redis_client.aset(task_key, task_model.model_dump())

        await LinsightExecuteTaskDao.update_by_id(task_id, user_input=user_input,
                                                  status=ExecuteTaskStatusEnum.USER_INPUT_COMPLETED)

    # 获取执行任务信息
    @retry_async(num_retries=3, delay=1)
    async def get_execution_task(self, task_id: str) -> LinsightExecuteTask | None:
        """
        获取执行任务信息
        :param task_id: 任务ID
        :return: 执行任务模型
        """
        task_key = f"{self._execution_tasks_key}{task_id}"
        task_data = await self._redis_client.aget(task_key)

        if task_data:
            return LinsightExecuteTask.model_validate(task_data)

        raise ValueError(f"Task with ID {task_id} not found in Redis.")

    # 写入任务步骤
    @retry_async(num_retries=3, delay=1)
    async def set_execution_task_steps(self, task_id: str, event: ExecStep):
        """
        设置执行任务步骤
        :param event:
        :param task_id: 任务ID
        """

        task_key = f"{self._execution_tasks_key}{task_id}"
        task_data = await self._redis_client.aget(task_key)

        if not task_data:
            raise ValueError(f"Task with ID {task_id} not found in Redis.")

        task_model = LinsightExecuteTask.model_validate(task_data)
        if task_model.history is None:
            task_model.history = []

        # 添加新的步骤到历史记录
        task_model.history.append(event.model_dump())

        # 更新任务步骤
        await self._redis_client.aset(task_key, task_model.model_dump())

        await LinsightExecuteTaskDao.update_by_id(task_id, history=task_model.history)
