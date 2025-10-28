import uuid
from datetime import datetime
from enum import Enum
from typing import Optional, Dict

from sqlalchemy import Enum as SQLEnum, DateTime, text, JSON
from sqlalchemy import CHAR, Column
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable


class ResourceTypeEnum(str, Enum):
    """资源类型枚举"""

    # 灵思会话
    LINSIGHT_SESSION = "linsight_session"
    # 工作台对话
    WORKBENCH_CHAT = "workbench_chat"
    # 工作流
    WORKFLOW = "workflow"
    # 技能
    SKILL = "skill"
    # 助手
    ASSISTANT = "assistant"


class ShareMode(str, Enum):
    """共享模式枚举"""
    # 只读
    READ_ONLY = "read_only"
    # 可编辑
    EDITABLE = "editable"


class ShareLinkStatusEnum(str, Enum):
    """共享链接状态枚举"""
    # 有效
    ACTIVE = "active"
    # 无效
    INACTIVE = "inactive"
    # 已过期
    EXPIRED = "expired"


class ShareLink(SQLModelSerializable, table=True):
    """
    共享链接模型
    """

    __tablename__ = 'share_link'

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, description='共享链接ID',
                    sa_column=Column(CHAR(36), unique=True, nullable=False, primary_key=True))
    share_token: str = Field(sa_column=Column(CHAR(36), index=True, unique=True), description='共享链接Token')

    resource_id: str = Field(sa_column=Column(CHAR(36), index=True), description='资源ID')

    resource_type: ResourceTypeEnum = Field(..., sa_column=Column(SQLEnum(ResourceTypeEnum)), description='资源类型')

    share_mode: ShareMode = Field(..., sa_column=Column(SQLEnum(ShareMode)), description='共享模式')
    status: ShareLinkStatusEnum = Field(default=ShareLinkStatusEnum.ACTIVE,
                                        sa_column=Column(SQLEnum(ShareLinkStatusEnum)), description='共享链接状态')
    access_count: int = Field(default=0, description='访问次数')
    meta_data: Optional[Dict] = Field(default=None, description='共享链接元数据', sa_type=JSON, nullable=True)
    expire_time: int = Field(default=0, description='过期时间，单位秒，0表示永不过期')

    create_user_id: str = Field(..., sa_column=Column(CHAR(36)), description='创建用户ID')

    create_time: datetime = Field(default_factory=datetime.now, description='创建时间',
                                  sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))

    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=True, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))
