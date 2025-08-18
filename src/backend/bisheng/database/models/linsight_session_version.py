import logging
from datetime import datetime
from enum import Enum
from typing import List, Dict, Optional

from sqlalchemy import Column, Text, JSON, Boolean, Enum as SQLEnum, DateTime, text, ForeignKey, CHAR, func
from sqlmodel import Field, select, col, update

from bisheng.database.base import async_session_getter, uuid_hex
from bisheng.database.models.base import SQLModelSerializable

logger = logging.getLogger(__name__)


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
    # 运行失败
    FAILED = "failed"
    # SOP 生成失败
    SOP_GENERATION_FAILED = "sop_generation_failed"
    # 终止
    TERMINATED = "terminated"


class LinsightSessionVersionBase(SQLModelSerializable):
    """
    灵思会话版本模型基类
    """
    session_id: str = Field(..., description='会话ID', sa_column=Column(CHAR(36),
                                                                        ForeignKey("message_session.chat_id"),
                                                                        nullable=False,
                                                                        index=True))
    user_id: int = Field(..., description='用户ID', foreign_key="user.user_id", nullable=False)
    question: str = Field(..., description='用户问题', sa_type=Text, nullable=False)
    title: Optional[str] = Field(None, description='会话标题', sa_type=Text, nullable=True)
    tools: Optional[List[Dict]] = Field(None, description='可用的工具列表', sa_type=JSON, nullable=True)
    # 个人知识库
    personal_knowledge_enabled: bool = Field(False, description='是否启用个人知识库', sa_type=Boolean)
    # 组织知识库
    org_knowledge_enabled: bool = Field(False, description='是否启用组织知识库', sa_type=Boolean)
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
    id: str = Field(default_factory=uuid_hex, description='会话版本ID',
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
    async def get_by_id(linsight_session_version_id: str) -> Optional[LinsightSessionVersion]:
        """
        根据灵思会话版本ID获取灵思会话版本
        :param linsight_session_version_id: 灵思会话版本ID
        :return: 灵思会话版本对象
        """
        async with async_session_getter() as session:
            statement = select(LinsightSessionVersion).where(
                LinsightSessionVersion.id == str(linsight_session_version_id))  # 显式转 str
            result = await session.exec(statement)
            return result.first()

    @staticmethod
    async def get_session_versions_by_session_id(session_id: str) -> List[LinsightSessionVersion]:
        """
        根据会话ID获取所有灵思会话版本
        :param session_id: 会话ID
        :return: 灵思会话版本列表
        """
        async with async_session_getter() as session:
            statement = select(LinsightSessionVersion).where(
                LinsightSessionVersion.session_id == str(session_id)).order_by(
                col(LinsightSessionVersion.version).desc())

            return (await session.exec(statement)).all()

    @staticmethod
    async def modify_sop_content(linsight_session_version_id: str, sop_content: str):
        """
        修改灵思会话版本的SOP内容
        :param linsight_session_version_id:
        :param sop_content:
        :return:
        """

        async with async_session_getter() as session:
            stmt = (
                update(LinsightSessionVersion)
                .where(col(LinsightSessionVersion.id) == str(linsight_session_version_id))  # 显式转 str
                .values(sop=sop_content)
            )

            result = await session.exec(stmt)
            if result.rowcount == 0:
                logger.warning(f"No session version found with ID: {linsight_session_version_id}")

            await session.commit()

    @staticmethod
    async def get_session_version_by_file_id(file_id: str) -> Optional[LinsightSessionVersion]:
        """
        根据文件ID获取灵思会话版本
        :param file_id: 文件ID
        :return: 灵思会话版本对象
        """
        async with async_session_getter() as session:
            statement = select(LinsightSessionVersion).where(
                func.json_search(LinsightSessionVersion.files, 'all', file_id)
            )
            result = await session.exec(statement)
            return result.first()


    # 根据任务状态获取灵思会话版本列表
    @staticmethod
    async def get_session_versions_by_status(status: SessionVersionStatusEnum) -> List[LinsightSessionVersion]:
        """
        根据任务状态获取灵思会话版本列表
        :param status: 会话版本状态
        :return: 灵思会话版本列表
        """
        async with async_session_getter() as session:
            statement = select(LinsightSessionVersion).where(
                LinsightSessionVersion.status == status
            )
            result = await session.exec(statement)
            return result.all()


    # 批量更新灵思会话版本状态
    @staticmethod
    async def batch_update_session_versions_status(session_version_ids: List[str], status: SessionVersionStatusEnum):
        """
        批量更新灵思会话版本状态
        :param session_version_ids: 会话版本ID列表
        :param status: 新的会话版本状态
        """
        async with async_session_getter() as session:
            stmt = (
                update(LinsightSessionVersion)
                .where(col(LinsightSessionVersion.id).in_(session_version_ids))
                .values(status=status)
            )
            await session.exec(stmt)
            await session.commit()