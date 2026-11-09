"""Current desktop message ratings. Notes stay out of model history and request bodies."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, String, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, LargeText, PreciseDateTime

_CATEGORIES = (
    "task-result",
    "instruction-following",
    "product-interaction",
    "service-stability",
    "resource-cost",
    "security-privacy-permission",
    "other",
)


class DshModelAuditMessageFeedback(SQLModelSerializable, table=True):
    __tablename__ = "dsh_model_audit_message_feedback"
    __table_args__ = (
        CheckConstraint("rating IN ('positive', 'negative')", name="ck_dma_feedback_rating"),
        CheckConstraint(
            "category IS NULL OR category IN (" + ", ".join(repr(item) for item in _CATEGORIES) + ")",
            name="ck_dma_feedback_category",
        ),
    )

    conversation_key: str = Field(sa_column=Column(String(64), primary_key=True))
    message_id: str = Field(sa_column=Column(String(256), primary_key=True))
    tenant_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=False, index=True))
    user_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    conversation_id: str = Field(sa_column=Column(String(256), nullable=False))
    rating: str = Field(sa_column=Column(String(16), nullable=False))
    category: str | None = Field(default=None, sa_column=Column(String(64)))
    note: str | None = Field(default=None, sa_column=Column(LargeText))
    event_seq: int = Field(sa_column=Column(BigInteger, nullable=False))
    received_at: datetime = Field(sa_column=Column(PreciseDateTime(), nullable=False))
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT, onupdate=text("CURRENT_TIMESTAMP")
        ),
    )
