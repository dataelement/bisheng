"""System Dictionary domain model - 系统字典领域模型"""

from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, Column, DateTime, Integer, String, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class DictionaryType(str, Enum):
    """专家职位相关字典类型"""

    EXPERT_POSITION = "expert_position"  # 岗位
    EXPERT_TITLE = "expert_title"  # 职务
    EXPERT_JOB_FAMILY = "expert_job_family"  # 职位族
    EXPERT_JOB_CATEGORY = "expert_job_category"  # 职位类


class SystemDictionary(SQLModelSerializable, table=True):
    """系统字典表

    存储各类枚举/字典型数据,按租户隔离。
    """

    __tablename__ = "system_dictionary"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "type",
            "value",
            name="uk_system_dictionary_tenant_type_value",
        ),
        {"comment": "System dictionary table for expert positions and other enums"},
    )

    id: int | None = Field(
        default=None,
        description="Dictionary entry ID",
        sa_column=Column(Integer, primary_key=True, autoincrement=True),
    )
    type: str = Field(
        ...,
        description="Dictionary type code",
        sa_column=Column(String(64), nullable=False, index=True, comment="Dictionary type"),
    )
    value: str = Field(
        ...,
        description="Dictionary value",
        sa_column=Column(String(255), nullable=False, comment="Dictionary value"),
    )
    sort_order: int = Field(
        default=0,
        description="Display sort order",
        sa_column=Column(
            Integer,
            nullable=False,
            server_default=text("0"),
            comment="Sort order",
        ),
    )
    is_enabled: bool = Field(
        default=True,
        description="Whether the entry is enabled",
        sa_column=Column(
            Boolean,
            nullable=False,
            server_default=text("1"),
            comment="Is enabled",
        ),
    )
    tenant_id: int | None = Field(
        default=None,
        description="Tenant ID",
        sa_column=Column(
            Integer,
            nullable=False,
            server_default=text("1"),
            index=True,
            comment="Tenant ID",
        ),
    )
    create_time: datetime = Field(
        default_factory=datetime.now,
        description="Creation time",
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        ),
    )
    update_time: datetime | None = Field(
        default=None,
        description="Last update time",
        sa_column=Column(
            DateTime,
            nullable=True,
            server_default=UPDATE_TIME_SERVER_DEFAULT,
        ),
    )
