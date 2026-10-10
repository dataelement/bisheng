from datetime import datetime

from sqlalchemy import CHAR, BigInteger, Column, DateTime, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class InformationArticleSyncState(SQLModelSerializable, table=True):
    """Public cross-node progress for one Information source."""

    __tablename__ = "information_article_sync_state"

    source_id: str = Field(sa_column=Column(CHAR(36), nullable=False, primary_key=True))
    article_cursor_create_time: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    processed_remote_sync_at: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    processed_article_list_updated_at: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    create_time: datetime = Field(
        default_factory=datetime.now,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True, server_default=UPDATE_TIME_SERVER_DEFAULT),
    )
