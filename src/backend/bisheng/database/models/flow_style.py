# Path: src/backend/bisheng/database/models/flowstyle.py

from typing import Optional
from uuid import UUID, uuid4

from bisheng.database.models.base import SQLModelSerializable
from sqlmodel import Field


class FlowStyleBase(SQLModelSerializable):
    color: str
    emoji: str
    flow_id: UUID = Field(default=None)


class FlowStyle(FlowStyleBase, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True, unique=True)


class FlowStyleUpdate(SQLModelSerializable):
    color: Optional[str] = None
    emoji: Optional[str] = None


class FlowStyleCreate(FlowStyleBase):
    pass


class FlowStyleRead(FlowStyleBase):
    id: UUID
