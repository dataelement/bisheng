
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple, Union
from uuid import UUID, uuid4

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from bisheng.database.models.role_access import AccessType, RoleAccess, RoleAccessDao
from bisheng.database.models.user_role import UserRoleDao
# if TYPE_CHECKING:
from pydantic import validator
from sqlalchemy import Column, DateTime, String, and_, delete, func, or_, text
from sqlmodel import JSON, Field, select, update


class MarkRecordStatus(Enum):
    DEFAULT = 1
    DONE = 2
    NO = 3


class MarkRecordBase(SQLModelSerializable):
    create_user: str = Field(index=True)
    create_id: int = Field(index=True)
    app_id: int = Field(index=True)
    task_id: int = Field(index=True)
    session_id: str = Field(index=True)
    status: Optional[int] = Field(index=False, default=1)
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=True,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))
    create_time: Optional[datetime] = Field(default=(datetime.now()).strftime('%Y-%m-%d %H:%M:%S'),
                                            index=True)


class MarkRecord(MarkRecordBase,table=True):
    id: Optional[int] = Field(default=None, primary_key=True)



class MarkRecordDao(MarkRecordBase):

    @classmethod
    def create_record(cls, record_info: MarkRecord) -> MarkRecord:
        with session_getter() as session:
            session.add(record_info)
            session.commit()
            session.refresh(record_info)
            return record_info 


    @classmethod
    def del_record(cls,task_id:int):
        with session_getter() as session:
            st = delete(MarkRecord).where(MarkRecord.task_id==task_id)
            session.exec(st)
            session.commit()
            return


    @classmethod
    def get_record(cls,task_id:int,session_id:str) -> MarkRecord:

        with session_getter() as session:
            statement = select(MarkRecord).where(MarkRecord.task_id==task_id).where(MarkRecord.session_id==session_id)
            return session.exec(statement).first()


