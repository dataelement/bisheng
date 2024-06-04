from datetime import datetime
from typing import Any, List, Optional, Tuple

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from sqlalchemy import Column, DateTime, and_, text
from sqlmodel import Field, select
from uuid import UUID


class EvaluationBase(SQLModelSerializable):
    user_id: Optional[int] = Field(index=True)
    assistant_id: Optional[UUID] = Field(index=True, description='助手ID')
    flow_id: Optional[str] = Field(index=True, description='技能ID')
    file_name: Optional[str] = Field(index=False, description='测试集文件名称')
    object_name: Optional[str] = Field(index=False, description='测试集数据 csv 文件存储路径')
    is_delete: Optional[int] = Field(default=0, description="是否删除")
    create_time: Optional[datetime] = Field(
        sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=True,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class Evaluation(EvaluationBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class EvaluationRead(EvaluationBase):
    id: int
    user_name: Optional[str]


class EvaluationCreate(EvaluationBase):
    pass


class EvaluationDao(EvaluationBase):
    @classmethod
    def query_by_id(cls, id: int) -> Evaluation:
        with session_getter() as session:
            return session.get(Evaluation, id)
