import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, CHAR, VARCHAR, Text, DateTime, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable


class ChannelInfoSource(SQLModelSerializable, table=True):
    """Channel Information Source Model"""

    __tablename__ = 'channel_info_source'

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, description='Channel Information Source ID',
                    sa_column=Column(CHAR(36), unique=True, nullable=False, primary_key=True))
    source_name: str = Field(..., description='Information Source Name', sa_column=Column(VARCHAR(255), nullable=False))
    source_icon: str = Field(None, description='Information Source Icon URL', sa_column=Column(VARCHAR(255), nullable=True))
    source_type: str = Field(..., description='Information Source Type', sa_column=Column(VARCHAR(50), nullable=False))
    description: str = Field(None, description='Information Source Description', sa_column=Column(Text, nullable=True))

    create_time: datetime = Field(default_factory=datetime.now, description='Creation Time',
                                  sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))

    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=True, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))
