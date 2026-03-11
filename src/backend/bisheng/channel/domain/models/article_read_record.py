import uuid
from datetime import datetime
from pydantic import BaseModel
from sqlalchemy import CHAR, Column, VARCHAR, DateTime, text, Integer, Index
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable


class ArticleReadRecord(SQLModelSerializable, table=True):
    """
    Article Read Record Model
    """

    __tablename__ = 'channel_article_read'
    __table_args__ = (
        Index('idx_user_article', 'user_id', 'article_id', unique=True),
    )

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, description='Record ID',
                    sa_column=Column(CHAR(36), unique=True, nullable=False, primary_key=True))
    article_id: str = Field(..., description='Article ID (from ES)', sa_column=Column(VARCHAR(255), nullable=False))
    user_id: int = Field(..., description='User ID', sa_column=Column(Integer, nullable=False))
    source_id: str = Field(None, description='Information Source ID', sa_column=Column(VARCHAR(255), nullable=True))

    create_time: datetime = Field(default_factory=datetime.now, description='Read Time',
                                  sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))

