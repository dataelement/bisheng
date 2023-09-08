from datetime import datetime
from typing import Dict, Optional
from uuid import UUID

from bisheng.database.models.base import SQLModelSerializable
from pydantic import validator
from sqlalchemy import Column, DateTime, text
from sqlmodel import JSON, Field

# Path: src/backend/bisheng/database/models/template.py


class TemplateSkillBase(SQLModelSerializable):
    name: str = Field(index=True)
    description: Optional[str] = Field(index=True)
    parameters: Optional[Dict] = Field(index=False)
    flow_id: Optional[UUID] = Field(index=True)
    api_parameters: Optional[str] = Field(index=False)
    create_time: Optional[datetime] = Field(
        sa_column=Column(DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP'), onupdate=text('CURRENT_TIMESTAMP')))

    @validator('parameters')
    def validate_json(v):
        # dict_keys(['description', 'name', 'id', 'data'])
        if not v:
            return v
        if not isinstance(v, dict):
            raise ValueError('Template must be a valid JSON')

        return v


class Template(TemplateSkillBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    parameters: Optional[Dict] = Field(default=None, sa_column=Column(JSON))


class TemplateRead(TemplateSkillBase):
    id: int
    name: str


class TemplateCreate(TemplateSkillBase):
    pass


class TemplateUpdate(TemplateSkillBase):
    name: Optional[str] = None
    description: Optional[str] = None
    parameters: Optional[Dict] = None
