from datetime import datetime
from enum import Enum

from sqlalchemy import Column, DateTime, Integer, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, JsonType
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
    layout_config: dict = Field(default_factory=dict, sa_column=Column(JsonType),
                                description="Front-end drag-and-drop layout configuration, such as position coordinates, size")
    style_config: dict = Field(default_factory=dict, sa_column=Column(JsonType),
                               description="Front-end style configurations such as themes, colors, etc.")

    user_id: int | None = Field(default=None, index=True, description='Create UserID, null indicates system creation')
    create_time: datetime | None = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: datetime | None = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT))


class DashboardDefault(SQLModelSerializable, table=True):
    __tablename__ = 'dashboard_default'
    user_id: int = Field(default=0, index=True, nullable=False, description='UsersID', primary_key=True)
    dashboard_id: int = Field(default=0, index=True, nullable=False, description="User's default KanbanID")
    create_time: datetime | None = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: datetime | None = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT))


class DashboardComponentBase(SQLModelSerializable):
    dashboard_id: int = Field(default=0, index=True, nullable=False, description='Kanban belongs toID')
    title: str = Field(default='', max_length=200, nullable=False)
    type: str = Field(default=DashboardType.CUSTOM.value, max_length=100, nullable=False)
    dataset_code: str = Field(default='', nullable=False, description="Dataset encoding of component association")
    data_config: dict = Field(default_factory=dict, sa_column=Column(JsonType), description="Component data configuration, such as query conditions, etc.")
    style_config: dict = Field(default_factory=dict, sa_column=Column(JsonType), description="Component style configuration, such as colors, fonts, etc.")

    create_time: datetime | None = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: datetime | None = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT))


class Dashboard(DashboardBase, table=True):
    __tablename__ = 'dashboard'
    id: int | None = Field(default=None, index=True, primary_key=True)
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            nullable=False,
            server_default=text("1"),
            index=True,
            comment="Tenant ID",
        ),
    )


class DashboardComponent(DashboardComponentBase, table=True):
    __tablename__ = 'dashboard_component'
    id: str = Field(default_factory=generate_uuid, index=True, primary_key=True)
