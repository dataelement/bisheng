from datetime import datetime
from enum import StrEnum

from sqlalchemy import Column, DateTime, Index, Text, func
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable


class CorrectionState(StrEnum):
    PENDING_ASSIGNMENT = "pending_assignment"
    PENDING_PROCESSING = "pending_processing"
    PENDING_REPLY = "pending_reply"
    REPLIED = "replied"


class AnswerCorrection(SQLModelSerializable, table=True):
    __tablename__ = "answer_correction"
    __table_args__ = (
        Index("ix_ac_submitter", "tenant_id", "submitter_id", "created_at", "id"),
        Index("ix_ac_app", "tenant_id", "app_id", "created_at", "id"),
        Index("ix_ac_assignee", "tenant_id", "assignee_id", "created_at", "id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int
    app_id: str = Field(max_length=64)
    answer_id: int
    submitter_id: int
    quote: str = Field(sa_column=Column(Text, nullable=False))
    correction: str = Field(sa_column=Column(Text, nullable=False))
    evidence: str = Field(sa_column=Column(Text, nullable=False))
    state: str = Field(default=CorrectionState.PENDING_ASSIGNMENT.value, max_length=32)
    knowledge_id: int | None = None
    assignee_id: int | None = None
    assigned_by: int | None = None
    assigned_at: datetime | None = None
    result: str | None = Field(default=None, sa_column=Column(Text))
    processed_by: int | None = None
    processed_at: datetime | None = None
    reply: str | None = Field(default=None, sa_column=Column(Text))
    replied_by: int | None = None
    replied_at: datetime | None = None
    created_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=func.current_timestamp()),
    )
    updated_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=func.current_timestamp()),
    )
