from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, JsonType, LargeText


class MessagePushOutboxStatus:
    """Status constants for message_push_outbox records."""

    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class MessagePushOutbox(SQLModelSerializable, table=True):
    """Persistent outbox for enterprise WeChat message pushes.

    Records are created synchronously when an in-app notification is sent.
    A Celery worker scans pending records and pushes them via the Shougang
    MADC API, updating retry_count / next_retry_at / failure_reason on failure.
    """

    __tablename__ = "message_push_outbox"

    id: int | None = Field(
        default=None,
        description="Outbox record ID",
        sa_column=Column(Integer, primary_key=True, autoincrement=True),
    )
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
    inbox_message_id: int | None = Field(
        default=None,
        description="Related inbox_message.id",
        sa_column=Column(Integer, index=True),
    )
    action_code: str = Field(
        ...,
        description="Notification action code, e.g. qa_expert_invited",
        sa_column=Column(String(64), nullable=False, index=True),
    )
    receiver_user_ids: list[int] = Field(
        default_factory=list,
        description="BiSheng receiver user IDs",
        sa_column=Column(JsonType, nullable=False),
    )
    wechat_user_ids: list[str] = Field(
        default_factory=list,
        description="Enterprise WeChat user IDs (MADC users field)",
        sa_column=Column(JsonType, nullable=False),
    )
    body: str = Field(
        ...,
        description="Rendered message body",
        sa_column=Column(LargeText, nullable=False),
    )
    status: str = Field(
        default=MessagePushOutboxStatus.PENDING,
        description="Outbox status: pending / sent / failed",
        sa_column=Column(String(32), nullable=False, index=True),
    )
    retry_count: int = Field(
        default=0,
        description="Number of push attempts already made",
        sa_column=Column(Integer, nullable=False, server_default=text("0")),
    )
    max_retries: int = Field(
        default=3,
        description="Maximum number of retries allowed",
        sa_column=Column(Integer, nullable=False, server_default=text("3")),
    )
    next_retry_at: datetime | None = Field(
        default=None,
        description="Next allowed retry time",
        sa_column=Column(DateTime, nullable=True, index=True),
    )
    failure_reason: str | None = Field(
        default=None,
        description="Failure reason from the last attempt",
        sa_column=Column(LargeText, nullable=True),
    )
    sent_at: datetime | None = Field(
        default=None,
        description="Successful push timestamp",
        sa_column=Column(DateTime, nullable=True),
    )
    create_time: datetime = Field(
        default_factory=datetime.now,
        description="Creation time",
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=UPDATE_TIME_SERVER_DEFAULT,
        ),
    )
