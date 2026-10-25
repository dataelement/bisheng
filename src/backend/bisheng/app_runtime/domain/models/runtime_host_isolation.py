"""Node-wide host isolation evidence, independent from manager heartbeats."""

from datetime import datetime

from sqlalchemy import BigInteger, Column
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import JsonType


class RuntimeHostIsolationReport(SQLModelSerializable, table=True):
    __tablename__ = "runtime_host_isolation_report"
    id: str = Field(primary_key=True, max_length=64)
    engine_id: str = Field(max_length=128)
    network_id: str = Field(max_length=128)
    config_digest: str = Field(max_length=64)
    rule_digest: str = Field(max_length=64)
    revision: int = Field(sa_column=Column(BigInteger, nullable=False))
    checked_at: datetime
    valid_until: datetime
    status: str = Field(max_length=16)
    checks: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
