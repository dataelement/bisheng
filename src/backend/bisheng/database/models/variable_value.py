from datetime import datetime
from typing import Optional
from uuid import UUID

from bisheng.database.models.base import SQLModelSerializable
# if TYPE_CHECKING:
from pydantic import validator
from sqlalchemy import Column, DateTime, text
from sqlmodel import Field


class VariableBase(SQLModelSerializable):
    flow_id: UUID = Field(index=True, description='所属的技能')
    node_id: str = Field(index=True, description='所属的node')
    variable_name: Optional[str] = Field(index=True, default=None, description='变量名')
    value_type: int = Field(index=False, description='变量类型，1=文本 2=list 3=file')
    is_option: int = Field(index=False, default=1, description='是否必填 1=必填 0=非必填')
    value: str = Field(index=False, default=0, description='变量值，当文本的时候，传入文本长度')
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))

    @validator('variable_name')
    def validate_length(v):
        # dict_keys(['description', 'name', 'id', 'data'])
        if not v:
            return v
        if len(v) > 50:
            v = v[:50]

        return v

    @validator('value')
    def validate_value(v):
        # dict_keys(['description', 'name', 'id', 'data'])
        if not v:
            return v

        v = ','.join(set(v.split(',')))
        return v


class Variable(VariableBase, table=True):
    __tablename__ = 't_variable_value'
    id: Optional[int] = Field(default=None, primary_key=True)


class VariableCreate(VariableBase):
    pass


class VariableRead(VariableBase):
    id: int
