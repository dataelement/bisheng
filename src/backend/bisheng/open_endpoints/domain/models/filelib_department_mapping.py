from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class FilelibDepartmentMapping(SQLModelSerializable, table=True):
    __tablename__ = "filelib_department_mapping"
    __table_args__ = (
        UniqueConstraint("external_department_id", name="uk_filelib_dept_map_external_department_id"),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(Integer, primary_key=True, autoincrement=True),
    )
    external_department_id: str = Field(
        sa_column=Column(
            String(128),
            nullable=False,
            comment="External department identifier from the upstream system",
        ),
    )
    external_department_name: str | None = Field(
        default=None,
        sa_column=Column(
            String(256),
            nullable=True,
            comment="External department display name from the upstream system",
        ),
    )
    org_code: str = Field(
        sa_column=Column(
            String(128),
            nullable=False,
            comment="Organization code mapped to department.external_id",
        ),
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        ),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=UPDATE_TIME_SERVER_DEFAULT,
        ),
    )
