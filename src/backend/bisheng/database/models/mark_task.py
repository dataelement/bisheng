from datetime import datetime
from enum import Enum
from typing import List, Optional

# if TYPE_CHECKING:
from sqlalchemy import Column, DateTime, and_, delete, func, or_, text
from sqlmodel import Field, select, update

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_sync_db_session


class MarkTaskStatus(Enum):
    DEFAULT = 1
    DONE = 2
    ING = 3


class MarkTaskBase(SQLModelSerializable):
    create_user: str = Field(index=True)
    create_id: int = Field(index=True)
    app_id: str = Field(index=False, max_length=2048)
    process_users: str = Field(index=False)  # 23,2323
    mark_user: Optional[str] = Field(default=None, index=True, nullable=True)
    status: Optional[int] = Field(index=False, default=1)
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class MarkTask(MarkTaskBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class MarkTaskRead(MarkTaskBase):
    id: Optional[int] = None
    mark_process: Optional[List[str]] = None


class MarkTaskDao(MarkTaskBase):

    @classmethod
    def create_task(cls, task_info: MarkTask) -> MarkTask:
        with get_sync_db_session() as session:
            session.add(task_info)
            session.commit()
            session.refresh(task_info)
            return task_info

    @classmethod
    def delete_task(cls, task_id: int):
        with get_sync_db_session() as session:
            st = delete(MarkTask).where(MarkTask.id == task_id)
            session.exec(st)
            session.commit()

    @classmethod
    def get_task_byid(cls, task_id: int) -> MarkTask:
        with get_sync_db_session() as session:
            statement = select(MarkTask).where(MarkTask.id == task_id)
            return session.exec(statement).first()

    @classmethod
    def get_task(cls, user_id: int) -> MarkTask:
        with get_sync_db_session() as session:
            statement = select(MarkTask).where(MarkTask.process_users.like('%{}%'.format(user_id)))
            return session.exec(statement).first()

    @classmethod
    def get_task_list_byuid(cls, user_id: int, task_id: int) -> MarkTask:
        with get_sync_db_session() as session:
            statement = select(MarkTask).where(MarkTask.id == task_id)
            return session.exec(statement).first()

    @classmethod
    def update_task(cls, task_id: int, status: int):
        with get_sync_db_session() as session:
            st = update(MarkTask).where(MarkTask.id == task_id).values(status=status)
            session.exec(st)
            session.commit()

    @classmethod
    def get_all_task(
            cls,
            page_size: int = 10,
            page_num: int = 1,
    ):
        with get_sync_db_session() as session:
            statement = select(MarkTask)
            total_count_query = select(func.count()).select_from(statement.alias('subquery'))
            statement = statement.order_by(MarkTask.create_time.desc())
            total_count = session.execute(total_count_query).scalar()
            statement = statement.limit(page_size).offset((page_num - 1) * page_size)
            return session.exec(statement).all(), total_count

    @classmethod
    def get_task_list(
            cls,
            status: int,
            create_id: Optional[int],
            user_id: Optional[int],
            page_size: int = 10,
            page_num: int = 1,
    ):
        with get_sync_db_session() as session:
            statement = select(MarkTask)

            filter = []
            filter_or = []
            if status:
                filter.append(MarkTask.status == status)
                if user_id:
                    filter.append(func.find_in_set(user_id, MarkTask.process_users) > 0)
            if create_id:
                filter.append(MarkTask.create_id == create_id)
            if user_id:
                filter_or.append(func.find_in_set(user_id, MarkTask.process_users) > 0)
                # filter_or.append(MarkTask.process_users.like('%{}%'.format(user_id)))
                if status:
                    filter_or.append(MarkTask.status == status)

            if filter and not filter_or:
                statement = statement.filter(*filter)
            if filter_or:
                statement = statement.filter(or_(and_(*filter), and_(*filter_or)))

            # Calculate total tasks
            total_count_query = select(func.count()).select_from(statement.alias('subquery'))
            statement = statement.order_by(MarkTask.create_time.desc())
            total_count = session.execute(total_count_query).scalar()
            statement = statement.limit(page_size).offset((page_num - 1) * page_size)
            return session.exec(statement).all(), total_count
