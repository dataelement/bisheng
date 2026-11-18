"""Explicit provider intent and frozen new-receiver initialization manifests.

No historical sharing is inferred or backfilled when these tables are created.
"""

from sqlalchemy import BigInteger, Column, String
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import JsonType


class ModelSharingIntent(SQLModelSerializable, table=True):
    __tablename__ = "llm_model_sharing_intent"

    server_id: int = Field(sa_column=Column(BigInteger, primary_key=True))
    tenant_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=False, index=True))
    enabled: bool
    version: int = Field(default=1)
    plan_id: str = Field(sa_column=Column(String(36), nullable=False))


class ModelSharingInitialization(SQLModelSerializable, table=True):
    __tablename__ = "llm_model_sharing_initialization"

    plan_id: str = Field(sa_column=Column(String(36), primary_key=True))
    tenant_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=False, index=True))
    server_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    child_ids: list[int] = Field(default_factory=list, sa_column=Column(JsonType, nullable=False))
    model_ids: list[int] = Field(default_factory=list, sa_column=Column(JsonType, nullable=False))
