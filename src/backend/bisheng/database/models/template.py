from datetime import datetime
from typing import Dict, Optional

from pydantic import model_validator
from sqlalchemy import JSON, Column, DateTime, text, String
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable


class TemplateSkillBase(SQLModelSerializable):
    name: str = Field(index=True)
    description: Optional[str] = Field(default=None, sa_column=Column(String(length=1000)))
    data: Optional[Dict] = Field(default=None, sa_column=Column(JSON))
    order_num: Optional[int] = Field(default=True, index=True)
    # 1 flow 5 assistant 10 workflow
    flow_type: Optional[int] = Field(default=1)
    flow_id: Optional[str] = Field(default=None, index=False)
    guide_word: Optional[str] = Field(default=None, sa_column=Column(String(length=1000)))
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class Template(TemplateSkillBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class TemplateRead(TemplateSkillBase):
    id: int
    name: str


class TemplateCreate(TemplateSkillBase):
    # 1 flow 5 assistant 10 workflow
    # flow_type: int = 1
    pass


class TemplateUpdate(SQLModelSerializable):
    name: Optional[str] = None
    description: Optional[str] = None
    data: Optional[Dict] = None
    order_num: Optional[int] = None
    guide_word: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def convert_field(cls, values: dict) -> dict:
        if values.get("order_num", None):
            values['order_num'] = int(float(values['order_num']))
        return values
