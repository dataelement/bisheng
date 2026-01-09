from datetime import datetime
from typing import Optional, List

# if TYPE_CHECKING:
from pydantic import field_validator
from sqlalchemy import Column, DateTime, text
from sqlmodel import Field, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_sync_db_session


class VariableBase(SQLModelSerializable):
    flow_id: str = Field(index=True, description='Belonging Skills')
    version_id: int = Field(description='Version of the skill to which it belongs')
    node_id: str = Field(index=True, description='belong tonode')
    variable_name: Optional[str] = Field(index=True, default=None, description='Variables')
    value_type: int = Field(index=False, description='Variable type1=Text 2=list 3=file')
    is_option: int = Field(index=False, default=1, description='Required? 1=Required 0=Price is not required')
    value: str = Field(index=False, default=0, description='variable value, the length of the incoming text when the text is')
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))

    @field_validator('variable_name')
    @classmethod
    def validate_length(cls, v):
        # dict_keys(['description', 'name', 'id', 'data'])
        if not v:
            return v
        if len(v) > 50:
            v = v[:50]

        return v

    @field_validator('value')
    @classmethod
    def validate_value(cls, v):
        # dict_keys(['description', 'name', 'id', 'data'])
        if not v:
            return v
        # Deduplication keeps the original order
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
        Create New variant
        """
        with get_sync_db_session() as session:
            db_variable = Variable.from_orm(variable)
            session.add(db_variable)
            session.commit()
            session.refresh(db_variable)
            return db_variable

    @classmethod
    def get_variables(cls, flow_id: str, node_id: str, variable_name: str, version_id: int) -> List[Variable]:
        with get_sync_db_session() as session:
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
        Copy the version of the form data to In the new version
        """
        with get_sync_db_session() as session:
            query = select(Variable).where(Variable.flow_id == flow_id, Variable.version_id == old_version_id)
            old_version = session.exec(query).all()
            for one in old_version:
                new_version = Variable.from_orm(one)
                new_version.id = None
                new_version.version_id = version_id
                session.add(new_version)
            session.commit()
            return old_version
