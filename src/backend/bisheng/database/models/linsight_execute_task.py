from datetime import datetime
from enum import Enum
from typing import Optional, Dict, List

from sqlalchemy import Enum as SQLEnum, Column, JSON, DateTime, text, CHAR, ForeignKey, update
from sqlmodel import Field, select, col

from bisheng.core.database import get_async_db_session
from bisheng.database.base import uuid_hex
from bisheng.common.models.base import SQLModelSerializable


class ExecuteTaskTypeEnum(str, Enum):
    """
    灵思执行任务类型枚举
    """
    # 单体任务
    SINGLE = "single"
    # 拥有子任务
    COMPOSITE = "composite"


class ExecuteTaskStatusEnum(str, Enum):
    """
    灵思执行任务状态枚举
    """
    # 未开始
    NOT_STARTED = "not_started"
    # 进行中
    IN_PROGRESS = "in_progress"
    # 成功
    SUCCESS = "success"
    # 等待用户输入
    WAITING_FOR_USER_INPUT = "waiting_for_user_input"
    # 用户输入完成
    USER_INPUT_COMPLETED = "user_input_completed"
    # 失败
    FAILED = "failed"
    # 终止
    TERMINATED = "terminated"


class LinsightExecuteTaskBase(SQLModelSerializable):
    """
    灵思执行任务模型基类
    """
    session_version_id: str = Field(..., description='会话版本ID',
                                    sa_column=Column(CHAR(36), ForeignKey("linsight_session_version.id"),
                                                     nullable=False))

    parent_task_id: Optional[str] = Field(None, description='父任务ID',
                                          sa_column=Column(CHAR(36), ForeignKey("linsight_execute_task.id"),
                                                           nullable=True))
    previous_task_id: Optional[str] = Field(None, description='上一个任务ID',
                                            sa_column=Column(CHAR(36),
                                                             nullable=True))
    next_task_id: Optional[str] = Field(None, description='下一个任务ID',
                                        sa_column=Column(CHAR(36),
                                                         nullable=True))
    task_type: ExecuteTaskTypeEnum = Field(..., description='任务类型',
                                           sa_column=Column(SQLEnum(ExecuteTaskTypeEnum), nullable=False))
    task_data: Optional[dict] = Field(None, description='任务数据', sa_type=JSON, nullable=True)

    # input_prompt: Optional[str] = Field(None, description='输入提示', sa_type=Text, nullable=True)
    # user_input: Optional[str] = Field(None, description='用户输入', sa_type=Text, nullable=True)
    history: Optional[List[Dict]] = Field(None, description='执行步骤记录', sa_type=JSON, nullable=True)
    status: ExecuteTaskStatusEnum = Field(ExecuteTaskStatusEnum.NOT_STARTED, description="任务状态",
                                          sa_column=Column(SQLEnum(ExecuteTaskStatusEnum), nullable=False))
    result: Optional[Dict] = Field(None, description='任务结果', sa_type=JSON, nullable=True)


class LinsightExecuteTask(LinsightExecuteTaskBase, table=True):
    """
    灵思执行任务模型, sop库也会引用这里的数据
    """
    id: str = Field(default_factory=uuid_hex, description='任务ID',
                    sa_column=Column(CHAR(36), unique=True, nullable=False, primary_key=True))

    create_time: datetime = Field(default_factory=datetime.now, description='创建时间',
                                  sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=True, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))

    __tablename__ = "linsight_execute_task"


class LinsightExecuteTaskDao(object):
    """
    灵思执行任务数据访问对象
    """

    @classmethod
    async def get_by_id(cls, task_id: str) -> Optional[LinsightExecuteTask]:
        """
        根据任务ID获取任务
        :param task_id: 任务ID
        :return: 任务对象
        """
        async with get_async_db_session() as session:
            statement = select(LinsightExecuteTask).where(LinsightExecuteTask.id == str(task_id))
            task = await session.exec(statement)
            return task.first()

    @classmethod
    async def get_by_session_version_id(cls, session_version_id: str, is_parent_task: bool = False) -> List[
        LinsightExecuteTask]:
        """
        根据会话版本ID获取所有任务
        :param is_parent_task:
        :param session_version_id: 会话版本ID
        :return: 任务列表
        """
        async with get_async_db_session() as session:
            statement = select(LinsightExecuteTask).where(
                LinsightExecuteTask.session_version_id == str(session_version_id))

            if is_parent_task:
                statement = statement.where(col(LinsightExecuteTask.parent_task_id).is_(None))

            tasks = await session.exec(statement)
            return tasks.all()

    @classmethod
    async def batch_create_tasks(cls, tasks: List[LinsightExecuteTask]) -> List[LinsightExecuteTask]:
        """
        批量创建任务
        :param tasks: 任务列表
        :return: 创建后的任务列表
        """
        async with get_async_db_session() as session:
            session.add_all(tasks)
            await session.commit()
            return tasks

    @classmethod
    async def update_by_id(cls, task_id: str, **kwargs) -> Optional[LinsightExecuteTask]:
        """
        根据任务ID更新任务
        :param task_id: 任务ID
        :param kwargs: 更新字段
        :return: 更新后的任务对象
        """
        async with get_async_db_session() as session:
            statement = select(LinsightExecuteTask).where(LinsightExecuteTask.id == task_id)
            task = await session.exec(statement)
            task = task.first()

            if not task:
                return None

            for key, value in kwargs.items():
                setattr(task, key, value)

            session.add(task)
            await session.commit()
            await session.refresh(task)
            return task

    # 根据session_version_id批量更新任务状态
    @classmethod
    async def batch_update_status_by_session_version_id(cls, session_version_ids: List[str],
                                                        status: ExecuteTaskStatusEnum,
                                                        where) -> None:
        """
        根据会话版本ID批量更新任务状态
        :param session_version_ids:
        :param status:
        :param where:
        :return:
        """

        async with get_async_db_session() as session:
            statement = (
                update(LinsightExecuteTask)
                .where(col(LinsightExecuteTask.session_version_id).in_(session_version_ids))  # 显式转 str
            )

            if where:
                statement = statement.where(*where)

            statement = statement.values(status=status)

            await session.exec(statement)
            await session.commit()
