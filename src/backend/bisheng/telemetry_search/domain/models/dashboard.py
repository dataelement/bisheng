from datetime import datetime
from enum import Enum
from typing import Optional, Dict

from sqlalchemy import Column, DateTime, text, JSON
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.utils import generate_uuid


class DashboardStatus(Enum):
    DRAFT = "draft"
    PUBLISHED = "published"


# Define enumeration: clearly distinguish between different types of Kanban
class DashboardType(Enum):
    CUSTOM = "custom"  # User-defined Kanban
    PRESET_OSS = "preset_oss"  # Prebuilt open source boards
    PRESET_COMMERCIAL = "preset_commercial"  # Preset Business Kanban


class ComponentType(Enum):
    FILTER = "filter"  # Filter Components, The backend queries this component for information to stitch filtering criteria


class DashboardBase(SQLModelSerializable):
    title: str = Field(default='', max_length=200, nullable=False)
    description: str = Field(default='', max_length=500, nullable=False)
    status: str = Field(default=DashboardStatus.DRAFT.value, max_length=20, nullable=False)
    dashboard_type: str = Field(default=DashboardType.CUSTOM.value, max_length=20, nullable=False)
    layout_config: Dict = Field(default_factory=dict, sa_column=Column(JSON),
                                description="Front-end drag-and-drop layout configuration, such as position coordinates, size")
    style_config: Dict = Field(default_factory=dict, sa_column=Column(JSON),
                               description="Front-end style configurations such as themes, colors, etc.")

    user_id: Optional[int] = Field(default=None, index=True, description='Create UserID， nullIndicates system creation')
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class DashboardDefault(SQLModelSerializable, table=True):
    __tablename__ = 'dashboard_default'
    user_id: int = Field(default=0, index=True, nullable=False, description='UsersID', primary_key=True)
    dashboard_id: int = Field(default=0, index=True, nullable=False, description="User's default KanbanID")
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class DashboardComponentBase(SQLModelSerializable):
    dashboard_id: int = Field(default=0, index=True, nullable=False, description='Kanban belongs toID')
    title: str = Field(default='', max_length=200, nullable=False)
    type: str = Field(default=DashboardType.CUSTOM.value, max_length=100, nullable=False)
    dataset_code: str = Field(default='', nullable=False, description="Dataset encoding of component association")
    data_config: Dict = Field(default_factory=dict, sa_column=Column(JSON), description="Component data configuration, such as query conditions, etc.")
    style_config: Dict = Field(default_factory=dict, sa_column=Column(JSON), description="Component style configuration, such as colors, fonts, etc.")

    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class Dashboard(DashboardBase, table=True):
    __tablename__ = 'dashboard'
    id: Optional[int] = Field(default=None, index=True, primary_key=True)


class DashboardComponent(DashboardComponentBase, table=True):
    __tablename__ = 'dashboard_component'
    id: str = Field(default_factory=generate_uuid, index=True, primary_key=True)
