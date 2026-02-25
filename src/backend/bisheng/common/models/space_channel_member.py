from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column, CHAR, Enum as SQLEnum, DateTime, text, Boolean
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable


class BusinessTypeEnum(str, Enum):
    SPACE = 'space'
    CHANNEL = 'channel'


class UserRoleEnum(str, Enum):
    CREATOR = 'creator'
    ADMIN = 'admin'
    MEMBER = 'member'


class SpaceChannelMember(SQLModelSerializable, table=True):
    __tablename__ = 'space_channel_member'
    id: Optional[int] = Field(default=None, primary_key=True)

    business_id: str = Field(..., description='Business ID', sa_column=Column(CHAR(36), nullable=False, index=True))
    business_type: BusinessTypeEnum = Field(...,
                                            sa_column=Column(SQLEnum(BusinessTypeEnum), nullable=False, index=True))
    user_id: int = Field(..., description='User ID', nullable=False)
    user_role: UserRoleEnum = Field(..., description='User Role',
                                    sa_column=Column(SQLEnum(UserRoleEnum), nullable=False))
    status: bool = Field(default=True, description='Membership Status', sa_type=Boolean, nullable=False)

    create_time: datetime = Field(default_factory=datetime.now, description='Creation Time',
                                  sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))

    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=True, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))
