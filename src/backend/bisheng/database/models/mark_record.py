from datetime import datetime
from enum import Enum
from typing import List, Optional

# if TYPE_CHECKING:
from sqlalchemy import Column, DateTime, delete, text
from sqlmodel import Field, select

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable


class MarkRecordStatus(Enum):
    DEFAULT = 1
    DONE = 2
    NO = 3


class MarkRecordBase(SQLModelSerializable):
    create_user: str = Field(index=True)
    flow_type: int = Field(index=True)
    create_id: int = Field(index=True)
    app_id: int = Field(index=True, nullable=True)
    task_id: int = Field(index=True)
    session_id: str = Field(index=True)
    status: int = Field(index=False, default=1)
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=True, server_default=text('CURRENT_TIMESTAMP'), onupdate=text('CURRENT_TIMESTAMP')))
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))


class MarkRecord(MarkRecordBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class MarkRecordDao(MarkRecordBase):

    @classmethod
    def update_record(cls, record_info: MarkRecord) -> MarkRecord:
        with session_getter() as session:
            session.add(record_info)
            session.commit()
            session.refresh(record_info)
            return record_info

    @classmethod
    def get_prev_task(cls, user_id: int, task_id: int):
        with session_getter() as session:
            statement = select(MarkRecord).where(MarkRecord.create_id == user_id).where(
                MarkRecord.task_id == task_id).order_by(MarkRecord.id)
            return session.exec(statement).all()

    @classmethod
    def create_record(cls, record_info: MarkRecord) -> MarkRecord:
        with session_getter() as session:
            session.add(record_info)
            session.commit()
            session.refresh(record_info)
            return record_info

    @classmethod
    def del_record(cls, task_id: int):
        with session_getter() as session:
            st = delete(MarkRecord).where(MarkRecord.task_id == task_id)
            session.exec(st)
            session.commit()
            return

    @classmethod
    def del_task_chat(cls, task_id: int, session_id: str):
        with session_getter() as session:
            st = delete(MarkRecord).where(MarkRecord.task_id == task_id).where(MarkRecord.session_id == session_id)
            session.exec(st)
            session.commit()
            return

    @classmethod
    def get_list_by_taskid(cls, task_id: int):
        with session_getter() as session:
            statement = select(MarkRecord).where(MarkRecord.task_id == task_id)
            return session.exec(statement).all()

    @classmethod
    def get_count(cls, task_id: int):
        with session_getter() as session:
            sql = text(
                "select create_user,count(*) as user_count,create_id from markrecord where task_id=:task_id group by create_id")
            query = session.execute(sql, {"task_id": task_id}).fetchall()
            return query

    @classmethod
    def get_record(cls, task_id: int, session_id: str) -> MarkRecord:

        with session_getter() as session:
            statement = select(MarkRecord).where(MarkRecord.task_id == task_id).where(
                MarkRecord.session_id == session_id)
            return session.exec(statement).first()

    @classmethod
    def filter_records(cls, task_id: int, chat_ids: list[str] = None, status: int = None, mark_user: int = None) -> \
            List[MarkRecord]:
        statement = select(MarkRecord).where(MarkRecord.task_id == task_id)
        if chat_ids:
            statement = statement.where(MarkRecord.session_id.in_(chat_ids))
        if status is not None:
            statement = statement.where(MarkRecord.status == status)
        if mark_user is not None:
            statement = statement.where(MarkRecord.create_user == str(mark_user))
        with session_getter() as session:
            return session.exec(statement).all()
