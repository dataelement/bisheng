from datetime import datetime
from typing import Optional

from bisheng.database.models.base import SQLModelSerializable
from sqlalchemy import Column, DateTime, text
from sqlmodel import Field


class ParamBase(SQLModelSerializable):
    flow_id: str = Field(index=True, description='所属的技能')
    node_id: str = Field(index=True, description='所属的node')
    variable_name: str = Field(index=True, description='变量名')
    value_type: int = Field(index=False, description='变量类型，1=文本 2=list')
    value: str = Field(index=False, default=0, description='变量值，当文本的时候，传入文本长度')
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class ParamList(ParamBase, table=True):
    __tablename__ = 't_variable_value'
    id: Optional[int] = Field(default=None, primary_key=True)


class ParamListCreate(ParamBase):
    pass


class ParamListRead(ParamBase):
    id: int
