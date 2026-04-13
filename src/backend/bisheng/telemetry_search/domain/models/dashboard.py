from datetime import datetime
from enum import Enum
from typing import Optional, Dict

from pydantic import ConfigDict
from sqlalchemy import Column, JSON, DateTime, text, CLOB, Integer
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.utils import generate_uuid


class DashboardStatus(Enum):
    DRAFT = "draft"
    PUBLISHED = "published"

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

# Define enumeration: clearly distinguish between different types of Kanban
class DashboardType(Enum):
    CUSTOM = "custom"  # User-defined Kanban
    PRESET_OSS = "preset_oss"  # Prebuilt open source boards
    PRESET_COMMERCIAL = "preset_commercial"  # Preset Business Kanban


class ComponentType(Enum):
    FILTER = "filter"  # Filter Components, The backend queries this component for information to stitch filtering criteria


class DashboardBase(SQLModelSerializable):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    title: str = Field(default='', max_length=200, nullable=False)
    description: str = Field(default='', max_length=500, nullable=False)
    status: str = Field(default=DashboardStatus.DRAFT.value, max_length=20, nullable=False)
    dashboard_type: str = Field(default=DashboardType.CUSTOM.value, max_length=20, nullable=False)
    layout_config: Dict = Field(default_factory=dict, sa_column=Column(DMJSON),
                                description="Front-end drag-and-drop layout configuration, such as position coordinates, size")
    style_config: Dict = Field(default_factory=dict, sa_column=Column(DMJSON),
                               description="Front-end style configurations such as themes, colors, etc.")

    user_id: Optional[int] = Field(default=None, index=True, description='Create UserID， nullIndicates system creation')
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))


class DashboardDefault(SQLModelSerializable, table=True):
    __tablename__ = 'dashboard_default'
    user_id: int = Field(default=0, index=True, nullable=False, description='UsersID', primary_key=True)
    dashboard_id: int = Field(default=0, index=True, nullable=False, description="User's default KanbanID")
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))


class DashboardComponentBase(SQLModelSerializable):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    dashboard_id: int = Field(default=0, index=True, nullable=False, description='Kanban belongs toID')
    title: str = Field(default='', max_length=200, nullable=False)
    type: str = Field(default=DashboardType.CUSTOM.value, max_length=100, nullable=False)
    dataset_code: str = Field(default='', nullable=False, description="Dataset encoding of component association")
    data_config: Dict = Field(default_factory=dict, sa_column=Column(DMJSON), description="Component data configuration, such as query conditions, etc.")
    style_config: Dict = Field(default_factory=dict, sa_column=Column(DMJSON), description="Component style configuration, such as colors, fonts, etc.")


    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))


class Dashboard(DashboardBase, table=True):
    __tablename__ = 'dashboard'
    id: Optional[int] = Field(default=None, sa_column=Column(Integer, primary_key=True, autoincrement=True))


class DashboardComponent(DashboardComponentBase, table=True):
    __tablename__ = 'dashboard_component'
    id: str = Field(default_factory=generate_uuid, index=True, primary_key=True)
