"""Opaque precheck confirmation plans; creating one never fences a resource.

Only application owners write canonical, validated payloads and revision
manifests here. Actor references contain identifiers and narrowing metadata,
never access tokens, provider credentials, file content, or source configs.
"""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Column, Index, UniqueConstraint
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import JsonType


def operation_plan_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class KnowledgeOperationPlan(SQLModelSerializable, table=True):
    __tablename__ = "knowledge_operation_plan"
    __table_args__ = (
        UniqueConstraint("tenant_id", "operation", "operation_id", name="uk_kop_plan_operation"),
        Index("ix_kop_plan_expiry", "expires_at", "id"),
        Index("ix_kop_plan_actor", "tenant_id", "actor_user_id", "operation", "id"),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True, max_length=36)
    tenant_id: int = Field(index=True)
    actor_user_id: int
    actor_reference: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    operation: str = Field(max_length=48)
    space_id: int | None = Field(default=None, index=True)

    target_manifest: list[dict] = Field(default_factory=list, sa_column=Column(JsonType, nullable=False))
    target_revisions: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    source_revisions: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    parameters: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    request_hash: str = Field(max_length=64)
    impact: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    plan_digest: str = Field(max_length=64)
    expires_at: datetime

    # Null until execution reserves/consumes this plan under the owner's SQL
    # transaction. The same durable operation resumes after a partial failure.
    operation_id: str | None = Field(default=None, max_length=64)
    consumed_at: datetime | None = Field(default=None)
    create_time: datetime = Field(default_factory=operation_plan_now)
    update_time: datetime = Field(default_factory=operation_plan_now)
