from datetime import datetime
from enum import Enum
from typing import List, Optional, Tuple, Dict
from uuid import UUID, uuid4

from bisheng.database.base import session_getter, generate_uuid
from bisheng.database.models.base import SQLModelSerializable
from bisheng.database.models.role_access import AccessType, RoleAccess
from sqlalchemy import JSON, Column, DateTime, Text, and_, func, or_, text
from sqlmodel import Field, select
from enum import Enum


class LogType(Enum):
    STARTED = 1
    IN_PROGRESS = 2
    FINISHED = 3


class ScheduledTaskLogsBase(SQLModelSerializable):
    task_id: str = Field(index=True, description='任务的唯一标识符，用于关联和查询特定任务的记录')
    task_name: str = Field(index=True, description='任务的名称，便于识别任务')
    log_type: int = Field(description='标记日志的类型，如开始、结束、执行中')
    log_content: Optional[Dict] = Field(sa_column=Column(JSON), default=None,description='以 JSON 格式存储的日志详细内容，可包含复杂的结构化信息')
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))

class ScheduledTaskLogs(ScheduledTaskLogsBase, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True, unique=True)


class ScheduledTaskLogsDao(ScheduledTaskLogsBase):

    @classmethod
    def insert_one(cls, data: ScheduledTaskLogs) -> ScheduledTaskLogs:
        with session_getter() as session:
            session.add(data)
            session.commit()
            session.refresh(data)
            return data

    @classmethod
    def insert_batch(cls, logs: List[ScheduledTaskLogs]) -> List[ScheduledTaskLogs]:
        """
        批量插入多条 ScheduledTaskLogs 记录。

        :param logs: 包含 ScheduledTaskLogs 实例的列表
        :return: 插入后的 ScheduledTaskLogs 实例列表
        """
        with session_getter() as session:
            try:
                session.add_all(logs)
                session.commit()
                for log in logs:
                    session.refresh(log)
                return logs
            except Exception as e:
                session.rollback()
                raise e

    @classmethod
    def get_by_task_id(cls, task_id: str) -> List[ScheduledTaskLogs]:
        with session_getter() as session:
            return session.query(ScheduledTaskLogs).filter(ScheduledTaskLogs.task_id == task_id).all()

    @classmethod
    def get_by_task_name(cls, task_name: str) -> List[ScheduledTaskLogs]:
        with session_getter() as session:
            return session.query(ScheduledTaskLogs).filter(ScheduledTaskLogs.task_name == task_name).all()
