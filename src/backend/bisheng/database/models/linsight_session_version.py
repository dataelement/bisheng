import logging
from datetime import datetime
from enum import Enum
from typing import List, Dict, Optional

from sqlalchemy import Column, Text, JSON, Boolean, Enum as SQLEnum, DateTime, text, ForeignKey, CHAR, func
from sqlmodel import Field, select, col, update

from bisheng.core.database import get_async_db_session
from bisheng.database.base import uuid_hex
from bisheng.common.models.base import SQLModelSerializable

logger = logging.getLogger(__name__)


class SessionVersionStatusEnum(str, Enum):
    """
    Ideas Session Version Status Enumeration
    """
    # not implemented
    NOT_STARTED = "not_started"
    # Sedang berlangsung
    IN_PROGRESS = "in_progress"
    # Run Completed
    COMPLETED = "completed"
    #  has failed to run...
    FAILED = "failed"
    # SOP Generation Failed
    SOP_GENERATION_FAILED = "sop_generation_failed"
    # TERMINATION
    TERMINATED = "terminated"


class LinsightSessionVersionBase(SQLModelSerializable):
    """
    Inspiration Conversation Version Model Base Class
    """
    session_id: str = Field(..., description='SessionsID', sa_column=Column(CHAR(36),
                                                                        ForeignKey("message_session.chat_id"),
                                                                        nullable=False,
                                                                        index=True))
    user_id: int = Field(..., description='UsersID', foreign_key="user.user_id", nullable=False)
    question: str = Field(..., description='User Questions', sa_type=Text, nullable=False)
    title: Optional[str] = Field(None, description='Session title', sa_type=Text, nullable=True)
    tools: Optional[List[Dict]] = Field(None, description='List of available tools', sa_type=JSON, nullable=True)
    # Personal Knowledge Base
    personal_knowledge_enabled: bool = Field(False, description='Whether or not to enable Personal Knowledge Base', sa_type=Boolean)
    # Organization Knowledge Base
    org_knowledge_enabled: bool = Field(False, description='Whether to enable organization knowledge base', sa_type=Boolean)
    files: Optional[List[Dict]] = Field(None, description='Uploaded files list:', sa_type=JSON, nullable=True)
    sop: Optional[str] = Field(None, description='SOPContents', sa_type=Text, nullable=True)
    output_result: Optional[Dict] = Field(None, description='Output Results', sa_type=JSON, nullable=True)
    status: SessionVersionStatusEnum = Field(default=SessionVersionStatusEnum.NOT_STARTED, description='Session Version Status',
                                             sa_column=Column(SQLEnum(SessionVersionStatusEnum), nullable=False))
    score: Optional[int] = Field(None, description='Session Score', ge=1, le=5, nullable=True)
    # Execution Result Feedback Information
    execute_feedback: Optional[str] = Field(None, description='Execution Result Feedback Information', sa_type=Text, nullable=True)

    # Is there a re-execution
    has_reexecute: bool = Field(default=False, description='Is there a re-execution', sa_type=Boolean, nullable=False)

    # Version
    version: datetime = Field(default_factory=datetime.now, description='Session Version Created Time', sa_type=DateTime)


class LinsightSessionVersion(LinsightSessionVersionBase, table=True):
    """
    Inspiration Conversation Version Model
    """
    id: str = Field(default_factory=uuid_hex, description='Session VersionID',
                    sa_column=Column(CHAR(36), unique=True, nullable=False, primary_key=True))

    create_time: datetime = Field(default_factory=datetime.now, description='Creation Time',
                                  sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=True, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))

    __tablename__ = "linsight_session_version"


class LinsightSessionVersionDao(object):
    """
    Inspiration Session Version Data Access Objects
    """

    @staticmethod
    async def insert_one(session_version: LinsightSessionVersion) -> LinsightSessionVersion:
        """
        Insert an Invisible Sessions version record
        :param session_version: Inspiration Conversation Version Object
        :return: Invisible Conversation Version Object Created
        """

        async with get_async_db_session() as session:
            session.add(session_version)
            await session.commit()
            await session.refresh(session_version)
            return session_version

    @staticmethod
    async def get_by_id(linsight_session_version_id: str) -> Optional[LinsightSessionVersion]:
        """
        According to the Inspiration Conversation versionIDGet Ideas Conversation Version
        :param linsight_session_version_id: Inspiration Conversation VersionID
        :return: Inspiration Conversation Version Object
        """
        async with get_async_db_session() as session:
            statement = select(LinsightSessionVersion).where(
                LinsightSessionVersion.id == str(linsight_session_version_id))  # Explicit Transfer str
            result = await session.exec(statement)
            return result.first()

    @staticmethod
    async def get_session_versions_by_session_id(session_id: str) -> List[LinsightSessionVersion]:
        """
        By ConversationIDGet all Ideas Conversation versions
        :param session_id: SessionsID
        :return: Inspiration Session Version List
        """
        async with get_async_db_session() as session:
            statement = select(LinsightSessionVersion).where(
                LinsightSessionVersion.session_id == str(session_id)).order_by(
                col(LinsightSessionVersion.version).desc())

            return (await session.exec(statement)).all()

    @staticmethod
    async def modify_sop_content(linsight_session_version_id: str, sop_content: str):
        """
        Modify Inspiration Conversation Version ofSOPContents
        :param linsight_session_version_id:
        :param sop_content:
        :return:
        """

        async with get_async_db_session() as session:
            stmt = (
                update(LinsightSessionVersion)
                .where(col(LinsightSessionVersion.id) == str(linsight_session_version_id))  # Explicit Transfer str
                .values(sop=sop_content)
            )

            result = await session.exec(stmt)
            if result.rowcount == 0:
                logger.warning(f"No session version found with ID: {linsight_session_version_id}")

            await session.commit()

    @staticmethod
    async def get_session_version_by_file_id(file_id: str) -> Optional[LinsightSessionVersion]:
        """
        According to DOCUMENTIDGet Ideas Conversation Version
        :param file_id: Doc.ID
        :return: Inspiration Conversation Version Object
        """
        async with get_async_db_session() as session:
            statement = select(LinsightSessionVersion).where(
                func.json_search(LinsightSessionVersion.files, 'all', file_id)
            )
            result = await session.exec(statement)
            return result.first()

    # Get a list of Ideas session versions based on task status
    @staticmethod
    async def get_session_versions_by_status(status: SessionVersionStatusEnum) -> List[LinsightSessionVersion]:
        """
        Get a list of Ideas session versions based on task status
        :param status: Session Version Status
        :return: Inspiration Session Version List
        """
        async with get_async_db_session() as session:
            statement = select(LinsightSessionVersion).where(
                LinsightSessionVersion.status == status
            )
            result = await session.exec(statement)
            return result.all()

    # Bulk Update Ideas Session Version Status
    @staticmethod
    async def batch_update_session_versions_status(session_version_ids: List[str], status: SessionVersionStatusEnum,
                                                   **kwargs) -> None:
        """
        Bulk Update Ideas Session Version Status
        :param session_version_ids: Session VersionIDVertical
        :param status: New Session Version Status
        """
        async with get_async_db_session() as session:
            stmt = (
                update(LinsightSessionVersion)
                .where(col(LinsightSessionVersion.id).in_(session_version_ids))
                .values(status=status, **kwargs)  # Support for additional field updates
            )
            await session.exec(stmt)
            await session.commit()
