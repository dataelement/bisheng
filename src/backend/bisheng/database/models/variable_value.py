from datetime import datetime
from typing import Optional, List
from uuid import UUID

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
# if TYPE_CHECKING:
from pydantic import validator
from sqlalchemy import Column, DateTime, text
from sqlmodel import Field, select, or_


class VariableBase(SQLModelSerializable):
    flow_id: UUID = Field(index=True, description='所属的技能')
    version_id: int = Field(description='所属的技能版本')
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
        # 去重保持原来的顺序
        v_list = v.split(',')
        res = []
        for one in v_list:
            if one not in res:
                res.append(one)
        return ','.join(res)


class Variable(VariableBase, table=True):
    __tablename__ = 't_variable_value'
    id: Optional[int] = Field(default=None, primary_key=True)


class VariableCreate(VariableBase):
    pass


class VariableRead(VariableBase):
    id: int


class VariableDao(Variable):

    @classmethod
    def create_variable(cls, variable: Variable) -> Variable:
        """
        创建新变量
        """
        with session_getter() as session:
            db_variable = Variable.from_orm(variable)
            session.add(db_variable)
            session.commit()
            session.refresh(db_variable)
            return db_variable

    @classmethod
    def get_variables(cls, flow_id: str, node_id: str, variable_name: str, version_id: int) -> List[Variable]:
        with session_getter() as session:
            query = select(Variable).where(Variable.flow_id == flow_id)
            if node_id:
                query = query.where(Variable.node_id == node_id)
            if variable_name:
                query = query.where(Variable.variable_name == variable_name)
            if version_id:
                query = query.where(Variable.version_id == version_id)
            return session.exec(query.order_by(Variable.id.asc())).all()

    @classmethod
    def copy_variables(cls, flow_id: str, old_version_id: int, version_id: int) -> List[Variable]:
        """
        复制版本的表单数据到 新版本内
        """
        with session_getter() as session:
            query = select(Variable).where(Variable.flow_id == flow_id, Variable.version_id == old_version_id)
            old_version = session.exec(query).all()
            for one in old_version:
                new_version = Variable.from_orm(one)
                new_version.id = None
                new_version.version_id = version_id
                session.add(new_version)
            session.commit()
            return old_version

