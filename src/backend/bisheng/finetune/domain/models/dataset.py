from datetime import datetime

from sqlmodel import Column, DateTime, Field, Integer, text

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import JsonType
from bisheng.utils import generate_uuid


class FinetuneDataset(SQLModelSerializable, table=True):
    """Immutable upload version; bytes live in object storage, never on an API node."""

    id: str = Field(default_factory=generate_uuid, primary_key=True)
    name: str = Field(max_length=255)
    url: str = Field(max_length=512, index=True)
    purpose: str = Field(default="training", max_length=20)
    job_id: str | None = Field(default=None, max_length=64)
    report: dict = Field(sa_column=Column(JsonType, nullable=False))
    user_id: int
    tenant_id: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=False, index=True, server_default=text("1"))
    )
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    )
