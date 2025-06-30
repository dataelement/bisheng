import uuid
from datetime import datetime
from enum import Enum
from typing import List, Dict, Optional
from uuid import UUID

from sqlalchemy import Column, Text, JSON, Boolean, Enum as SQLEnum, DateTime, text, ForeignKey, CHAR
from sqlmodel import Field, select, col

from bisheng.database.base import async_session_getter
from bisheng.database.models.base import SQLModelSerializable


class SessionVersionStatusEnum(str, Enum):
    """
    灵思会话版本状态枚举
    """
    # 未执行
    NOT_STARTED = "not_started"
    # 进行中
    IN_PROGRESS = "in_progress"
    # 运行完成
    COMPLETED = "completed"
    # 终止
    TERMINATED = "terminated"


class LinsightSessionVersionBase(SQLModelSerializable):
    """
    灵思会话版本模型基类
    """
    session_id: UUID = Field(..., description='会话ID', sa_column=Column(CHAR(36),
                                                                         ForeignKey("message_session.chat_id"),
                                                                         nullable=False,
                                                                         index=True))
    user_id: int = Field(..., description='用户ID', foreign_key="user.user_id", nullable=False)
    question: str = Field(..., description='用户问题', sa_type=Text, nullable=False)
    tools: Optional[List[Dict]] = Field(None, description='可用的工具列表', sa_type=JSON, nullable=True)
    knowledge_enabled: bool = Field(False, description='是否启用知识库', sa_type=Boolean)
    files: Optional[List[Dict]] = Field(None, description='上传的文件列表', sa_type=JSON, nullable=True)
    sop: Optional[str] = Field(None, description='SOP内容', sa_type=Text, nullable=True)
    output_result: Optional[Dict] = Field(None, description='输出结果', sa_type=JSON, nullable=True)
    status: SessionVersionStatusEnum = Field(default=SessionVersionStatusEnum.NOT_STARTED, description='会话版本状态',
                                             sa_column=Column(SQLEnum(SessionVersionStatusEnum), nullable=False))
    score: Optional[int] = Field(None, description='会话评分', ge=1, le=5, nullable=True)
    # 执行结果反馈信息
    execute_feedback: Optional[str] = Field(None, description='执行结果反馈信息', sa_type=Text, nullable=True)

    # 是否有重新执行
    has_reexecute: bool = Field(default=False, description='是否有重新执行', sa_type=Boolean, nullable=False)

    # 版本
    version: datetime = Field(default_factory=datetime.now, description='会话版本创建时间', sa_type=DateTime)


class LinsightSessionVersion(LinsightSessionVersionBase, table=True):
    """
    灵思会话版本模型
    """
    id: UUID = Field(default_factory=uuid.uuid4, description='会话版本ID',
                     sa_column=Column(CHAR(36), unique=True, nullable=False, primary_key=True))

    create_time: datetime = Field(default_factory=datetime.now, description='创建时间',
                                  sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=True, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))

    __tablename__ = "linsight_session_version"


class LinsightSessionVersionDao(object):
    """
    灵思会话版本数据访问对象
    """

    @staticmethod
    async def insert_one(session_version: LinsightSessionVersion) -> LinsightSessionVersion:
        """
        插入一条灵思会话版本记录
        :param session_version: 灵思会话版本对象
        :return: 创建的灵思会话版本对象
        """

        async with async_session_getter() as session:
            session.add(session_version)
            await session.commit()
            await session.refresh(session_version)
            return session_version

    @staticmethod
    async def get_session_versions_by_session_id(session_id: UUID) -> List[LinsightSessionVersion]:
        """
        根据会话ID获取所有灵思会话版本
        :param session_id: 会话ID
        :return: 灵思会话版本列表
        """
        async with async_session_getter() as session:
            statement = select(LinsightSessionVersion).where(LinsightSessionVersion.session_id == session_id).order_by(
                col(LinsightSessionVersion.version).desc())

            return (await session.exec(statement)).all()
