from datetime import datetime
from typing import List, Optional

# if TYPE_CHECKING:
from sqlalchemy import Column, DateTime, text
from sqlmodel import Field

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable


class MarkAppUserBase(SQLModelSerializable):
    app_id: str = Field(index=True)
    user_id: int = Field(index=True)
    task_id: int = Field(index=True)
    create_id: int = Field(index=True)
    status: Optional[int] = Field(index=False, default=1)
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=True, server_default=text('CURRENT_TIMESTAMP'), onupdate=text('CURRENT_TIMESTAMP')))
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))


class MarkAppUser(MarkAppUserBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class MarkAppUserDao(MarkAppUserBase):

    @classmethod
    def create_task(cls, task_info: List[MarkAppUser]) -> List[MarkAppUser]:
        with session_getter() as session:
            session.add_all(task_info)
            session.commit()
            return task_info
