from datetime import datetime
from typing import List, Optional

# if TYPE_CHECKING:
from sqlalchemy import Column, DateTime, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_sync_db_session


class MarkAppUserBase(SQLModelSerializable):
    app_id: str = Field(index=True)
    user_id: int = Field(index=True)
    task_id: int = Field(index=True)
    create_id: int = Field(index=True)
    status: Optional[int] = Field(index=False, default=1)
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class MarkAppUser(MarkAppUserBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class MarkAppUserDao(MarkAppUserBase):

    @classmethod
    def create_task(cls, task_info: List[MarkAppUser]) -> List[MarkAppUser]:
        with get_sync_db_session() as session:
            session.add_all(task_info)
            session.commit()
            return task_info
