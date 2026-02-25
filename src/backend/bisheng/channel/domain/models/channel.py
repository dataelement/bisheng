import uuid
from datetime import datetime
from enum import Enum
from typing import List, Dict, Optional, Literal

from anthropic import BaseModel
from sqlalchemy import CHAR, Column, VARCHAR, JSON, Enum as SQLEnum, DateTime, Boolean, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable


class ChannelVisibilityEnum(str, Enum):
    """Channel Visibility Enumeration"""
    # Public
    PUBLIC = "public"
    # Private
    PRIVATE = "private"
    # Review required
    REVIEW = "review"


class ChannelRule(BaseModel):
    """Channel Filter Rule Model"""

    rule_type: Literal['include', 'exclude'] = Field(..., description='Rule Type: include or exclude')
    keywords: List[str] = Field(..., description='List of keywords for filtering')
    relation: Literal['and', 'or'] = Field(..., description='Relationship between keywords: and or or')


class ChannelFilterRules(BaseModel):
    """Channel Filter Rules Model"""

    rules: List[ChannelRule] = Field(..., description='List of filter rules')
    channel_type: Literal['main', 'sub'] = Field(..., description='Channel type: main or sub')
    name: Optional[str] = Field(None, description='Filter name, required for sub channel')


class Channel(SQLModelSerializable, table=True):
    """
    Channel Model
    """

    __tablename__ = 'channel'

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, description='Channel ID',
                    sa_column=Column(CHAR(36), unique=True, nullable=False, primary_key=True))
    name: str = Field(..., description='Channel Name', sa_column=Column(VARCHAR(255), nullable=False))
    source_list: List[str] = Field(default_factory=list, description='Data Source List',
                                   sa_column=Column(JSON, nullable=False))
    visibility: ChannelVisibilityEnum = Field(..., sa_column=Column(SQLEnum(ChannelVisibilityEnum)),
                                              description='Channel Visibility')
    filter_rules: List[Dict] = Field(default_factory=list, description='Filter Conditions',
                                     sa_column=Column(JSON, nullable=False))
    user_id: int = Field(..., description='UsersID', foreign_key="user.user_id", nullable=False)
    latest_article_update_time: datetime = Field(None, description='Latest Article Update Time',
                                                 sa_column=Column(DateTime, nullable=True))

    is_released: bool = Field(default=False, description='Whether the channel is released',
                              sa_column=Column(Boolean, nullable=False))

    create_time: datetime = Field(default_factory=datetime.now, description='Creation Time',
                                  sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))

    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=True, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))
