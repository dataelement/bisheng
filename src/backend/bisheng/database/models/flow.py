# Path: src/backend/bisheng/database/models/flow.py

from datetime import datetime
from typing import Dict, Optional
from uuid import UUID, uuid4

from bisheng.database.models.base import SQLModelSerializable
# if TYPE_CHECKING:
from pydantic import validator
from sqlalchemy import Column, DateTime, text
from sqlmodel import JSON, Field


class FlowBase(SQLModelSerializable):
    name: str = Field(index=True)
    user_id: Optional[int] = Field(index=True)
    description: Optional[str] = Field(index=False)
    data: Optional[Dict] = Field(default=None)
    logo: Optional[str] = Field(index=False)
    status: Optional[int] = Field(index=False, default=1)
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=True,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))
    create_time: Optional[datetime] = Field(default=(datetime.now()).strftime('%Y-%m-%d %H:%M:%S'),
                                            index=True)

    @validator('data')
    def validate_json(v):
        # dict_keys(['description', 'name', 'id', 'data'])
        if not v:
            return v
        if not isinstance(v, dict):
            raise ValueError('Flow must be a valid JSON')

        # data must contain nodes and edges
        if 'nodes' not in v.keys():
            raise ValueError('Flow must have nodes')
        if 'edges' not in v.keys():
            raise ValueError('Flow must have edges')

        return v


class Flow(FlowBase, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True, unique=True)
    data: Optional[Dict] = Field(default=None, sa_column=Column(JSON))
    # style: Optional['FlowStyle'] = Relationship(
    #     back_populates='flow',
    #     # use "uselist=False" to make it a one-to-one relationship
    #     sa_relationship_kwargs={'uselist': False},
    # )


class FlowCreate(FlowBase):
    flow_id: Optional[UUID]


class FlowRead(FlowBase):
    id: UUID
    user_name: Optional[str]


class FlowReadWithStyle(FlowRead):
    # style: Optional['FlowStyleRead'] = None
    total: Optional[int] = None


class FlowUpdate(SQLModelSerializable):
    name: Optional[str] = None
    description: Optional[str] = None
    data: Optional[Dict] = None
    status: Optional[int] = None
