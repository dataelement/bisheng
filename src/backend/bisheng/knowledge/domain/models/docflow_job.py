"""Remote parsing and ingestion checkpoints (new table, auto-discovered)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, JsonType


class DocFlowJob(SQLModelSerializable, table=True):
    __tablename__ = "knowledge_docflow_job"

    id: str = Field(primary_key=True, max_length=64)
    tenant_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    scope: str = Field(default="parse", max_length=16)
    state: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    )
    update_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT)
    )
