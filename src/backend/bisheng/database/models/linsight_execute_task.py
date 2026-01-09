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
    Idea execution task type enumeration
    """
    # Single Task
    SINGLE = "single"
    # Has subtasks
    COMPOSITE = "composite"


class ExecuteTaskStatusEnum(str, Enum):
    """
    Idea Execution Task Status Enumeration
    """
    # Not Started
    NOT_STARTED = "not_started"
    # Sedang berlangsung
    IN_PROGRESS = "in_progress"
    # Berhasil
    SUCCESS = "success"
    # Waiting for user input
    WAITING_FOR_USER_INPUT = "waiting_for_user_input"
    # User input complete
    USER_INPUT_COMPLETED = "user_input_completed"
    # Kalah
    FAILED = "failed"
    # TERMINATION
    TERMINATED = "terminated"


class LinsightExecuteTaskBase(SQLModelSerializable):
    """
    Idea Execution Task Model Base Class
    """
    session_version_id: str = Field(..., description='Session VersionID',
                                    sa_column=Column(CHAR(36), ForeignKey("linsight_session_version.id"),
                                                     nullable=False))

    parent_task_id: Optional[str] = Field(None, description='Parent Task:ID',
                                          sa_column=Column(CHAR(36), ForeignKey("linsight_execute_task.id"),
                                                           nullable=True))
    previous_task_id: Optional[str] = Field(None, description='Previous TaskID',
                                            sa_column=Column(CHAR(36),
                                                             nullable=True))
    next_task_id: Optional[str] = Field(None, description='[patterns/patterns_ParallelJoin.xml?ROU_NEXT_TASK] Next TaskID',
                                        sa_column=Column(CHAR(36),
                                                         nullable=True))
    task_type: ExecuteTaskTypeEnum = Field(..., description='Task type',
                                           sa_column=Column(SQLEnum(ExecuteTaskTypeEnum), nullable=False))
    task_data: Optional[dict] = Field(None, description='Task Data', sa_type=JSON, nullable=True)

    # input_prompt: Optional[str] = Field(None, description='Enter a prompt', sa_type=Text, nullable=True)
    # user_input: Optional[str] = Field(None, description='User input', sa_type=Text, nullable=True)
    history: Optional[List[Dict]] = Field(None, description='Execute Step Record', sa_type=JSON, nullable=True)
    status: ExecuteTaskStatusEnum = Field(ExecuteTaskStatusEnum.NOT_STARTED, description="Status Misi",
                                          sa_column=Column(SQLEnum(ExecuteTaskStatusEnum), nullable=False))
    result: Optional[Dict] = Field(None, description='Result of Task', sa_type=JSON, nullable=True)


class LinsightExecuteTask(LinsightExecuteTaskBase, table=True):
    """
    Ideas Execution Task Model, sopThe library will also reference the data here
    """
    id: str = Field(default_factory=uuid_hex, description='TaskID',
                    sa_column=Column(CHAR(36), unique=True, nullable=False, primary_key=True))

    create_time: datetime = Field(default_factory=datetime.now, description='Creation Time',
                                  sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=True, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))

    __tablename__ = "linsight_execute_task"


class LinsightExecuteTaskDao(object):
    """
    Ideas Execution Task Data Access Objects
    """

    @classmethod
    async def get_by_id(cls, task_id: str) -> Optional[LinsightExecuteTask]:
        """
        By TaskIDGet Tasks
        :param task_id: TaskID
        :return: Task Objects
        """
        async with get_async_db_session() as session:
            statement = select(LinsightExecuteTask).where(LinsightExecuteTask.id == str(task_id))
            task = await session.exec(statement)
            return task.first()

    @classmethod
    async def get_by_session_version_id(cls, session_version_id: str, is_parent_task: bool = False) -> List[
        LinsightExecuteTask]:
        """
        Based on session versionIDGet all tasks
        :param is_parent_task:
        :param session_version_id: Session VersionID
        :return: Task list
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
        Batch Create Tasks
        :param tasks: Task list
        :return: Post-Created Task List
        """
        async with get_async_db_session() as session:
            session.add_all(tasks)
            await session.commit()
            return tasks

    @classmethod
    async def update_by_id(cls, task_id: str, **kwargs) -> Optional[LinsightExecuteTask]:
        """
        By TaskIDUpdate Details
        :param task_id: TaskID
        :param kwargs: Update fields
        :return: Updated task object
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

    # accordingsession_version_idBulk update task status
    @classmethod
    async def batch_update_status_by_session_version_id(cls, session_version_ids: List[str],
                                                        status: ExecuteTaskStatusEnum,
                                                        where) -> None:
        """
        Based on session versionIDBulk update task status
        :param session_version_ids:
        :param status:
        :param where:
        :return:
        """

        async with get_async_db_session() as session:
            statement = (
                update(LinsightExecuteTask)
                .where(col(LinsightExecuteTask.session_version_id).in_(session_version_ids))  # Explicit Transfer str
            )

            if where:
                statement = statement.where(*where)

            statement = statement.values(status=status)

            await session.exec(statement)
            await session.commit()
