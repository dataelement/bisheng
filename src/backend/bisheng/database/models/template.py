from datetime import datetime
from typing import Dict, Optional

from pydantic import model_validator
from sqlalchemy import JSON, Column, DateTime, text, String
from sqlmodel import Field

from bisheng.database.models.base import SQLModelSerializable
from sqlalchemy import Integer

# 自定义 JSON 类型：自动处理字符串与字典的转换
from sqlalchemy.types import TypeDecorator, JSON
import json
class DMJSON(TypeDecorator):
    impl = JSON  # 底层依赖达梦的 JSON 类型
    def process_bind_param(self, value, dialect):
        # 写入数据库：字典转 JSON 字符串
        if value is None:
            return None
        return json.dumps(value)
    def process_result_value(self, value, dialect):
        # 读取数据库：JSON 字符串转字典
        if value is None:
            return None
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return {}
        return value

class TemplateBase(SQLModelSerializable):
    name: str = Field(index=True)
    description: str = Field(index=False)
    data: Optional[Dict] = Field(default=None, sa_column=Column(DMJSON))
    order_num: Optional[int] = Field(default=True, index=True)
    # 5 assistant 10 workflow
    flow_type: Optional[int] = Field(default=FlowType.WORKFLOW.value)
    flow_id: Optional[str] = Field(default=None, index=False)
    guide_word: Optional[str] = Field(default=None, sa_column=Column(String(length=1000)))
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class Template(TemplateSkillBase, table=True):
    # id: Optional[int] = Field(default=None, primary_key=True)
    id: Optional[int] = Field(default=None, sa_column=Column(Integer, primary_key=True, autoincrement=True))


class TemplateRead(TemplateBase):
    id: int
    name: str


class TemplateCreate(TemplateBase):
    # 5 assistant 10 workflow
    # flow_type: int = FlowType.WORKFLOW.value
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
