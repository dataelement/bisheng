import logging
from datetime import datetime
from enum import Enum

from sqlalchemy import CHAR, Boolean, Column, DateTime, ForeignKey, Integer, Text, text
from sqlalchemy import Enum as SQLEnum
from sqlmodel import Field, col, select, update

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, JsonType, json_search_exists
from bisheng.database.base import uuid_hex

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
    # Parked on an ask_user interrupt, waiting for the user's answer
    # (park-and-release). A dedicated state — NOT IN_PROGRESS — so the
    # worker-startup crash sweep (check_and_terminate_incomplete_tasks, which
    # terminates IN_PROGRESS tasks whose Redis owner key is gone) does not
    # mistake a legitimately parked task for a crashed one. Resume flips it back
    # to IN_PROGRESS.
    WAITING_FOR_USER_INPUT = "waiting_for_user_input"


class LinsightSessionVersionBase(SQLModelSerializable):
    """
    Inspiration Conversation Version Model Base Class
    """

    session_id: str = Field(
        ...,
        description="SessionsID",
        sa_column=Column(CHAR(36), ForeignKey("message_session.chat_id"), nullable=False, index=True),
    )
    user_id: int = Field(..., description="UsersID", foreign_key="user.user_id", nullable=False)
    question: str = Field(..., description="User Questions", sa_type=Text, nullable=False)
    title: str | None = Field(None, description="Session title", sa_type=Text, nullable=True)
    tools: list[dict] | None = Field(
        None, description="List of available tools", sa_column=Column(JsonType, nullable=True)
    )
    # Personal Knowledge Base
    personal_knowledge_enabled: bool = Field(
        False, description="Whether or not to enable Personal Knowledge Base", sa_type=Boolean
    )
    # Organization Knowledge Base
    org_knowledge_enabled: bool = Field(
        False, description="Whether to enable organization knowledge base", sa_type=Boolean
    )
    # Exact knowledge selection threaded from the daily picker (unified entry,
    # use_knowledge_base). These are the SPECIFIC ids the user chose, so the task
    # agent searches exactly those — not all KBs of a coarse type. organization =
    # NORMAL-type KB ids; knowledge_space = SPACE-type KB ids. Nullable for
    # backward compatibility with sessions created before this column existed.
    organization_knowledge_ids: list[int] | None = Field(
        None, description="Selected organization knowledge base ids", sa_column=Column(JsonType, nullable=True)
    )
    knowledge_space_ids: list[int] | None = Field(
        None, description="Selected knowledge space ids", sa_column=Column(JsonType, nullable=True)
    )
    files: list[dict] | None = Field(
        None, description="Uploaded files list:", sa_column=Column(JsonType, nullable=True)
    )
    # F035: per-task execution model id chosen at submit time (nullable; falls
    # back to the tenant linsight_default_model_id when empty).
    model: str | None = Field(None, description="Per-task execution model id", sa_type=Text, nullable=True)
    sop: str | None = Field(None, description="SOPContents", sa_type=Text, nullable=True)
    output_result: dict | None = Field(None, description="Output Results", sa_column=Column(JsonType, nullable=True))
    status: SessionVersionStatusEnum = Field(
        default=SessionVersionStatusEnum.NOT_STARTED,
        description="Session Version Status",
        # Plain VARCHAR (no native ENUM / CHECK): a native ENUM created at table
        # time freezes the allowed set, so a newly-added status like
        # WAITING_FOR_USER_INPUT is rejected with "Data truncated" on upgraded
        # DBs. Storage stays the enum NAME (back-compatible with existing rows).
        sa_column=Column(
            SQLEnum(SessionVersionStatusEnum, native_enum=False, length=50, create_constraint=False),
            nullable=False,
        ),
    )
    score: int | None = Field(None, description="Session Score", ge=1, le=5, nullable=True)
    # Execution Result Feedback Information
    execute_feedback: str | None = Field(
        None, description="Execution Result Feedback Information", sa_type=Text, nullable=True
    )

    # Is there a re-execution
    has_reexecute: bool = Field(default=False, description="Is there a re-execution", sa_type=Boolean, nullable=False)

    # Version
    version: datetime = Field(
        default_factory=datetime.now, description="Session Version Created Time", sa_type=DateTime
    )
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, server_default=text("1"), index=True, comment="Tenant ID"),
    )


class LinsightSessionVersion(LinsightSessionVersionBase, table=True):
    """
    Inspiration Conversation Version Model
    """

    id: str = Field(
        default_factory=uuid_hex,
        description="Session VersionID",
        sa_column=Column(CHAR(36), unique=True, nullable=False, primary_key=True),
    )

    create_time: datetime = Field(
        default_factory=datetime.now,
        description="Creation Time",
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    update_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=True, server_default=UPDATE_TIME_SERVER_DEFAULT)
    )

    __tablename__ = "linsight_session_version"


class LinsightSessionVersionDao:
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
    async def get_by_id(linsight_session_version_id: str) -> LinsightSessionVersion | None:
        """
        According to the Inspiration Conversation versionIDGet Ideas Conversation Version
        :param linsight_session_version_id: Inspiration Conversation VersionID
        :return: Inspiration Conversation Version Object
        """
        async with get_async_db_session() as session:
            statement = select(LinsightSessionVersion).where(
                LinsightSessionVersion.id == str(linsight_session_version_id)
            )  # Explicit Transfer str
            result = await session.exec(statement)
            return result.first()

    @staticmethod
    async def get_session_versions_by_session_id(session_id: str) -> list[LinsightSessionVersion]:
        """
        By ConversationIDGet all Ideas Conversation versions
        :param session_id: SessionsID
        :return: Inspiration Session Version List
        """
        async with get_async_db_session() as session:
            statement = (
                select(LinsightSessionVersion)
                .where(LinsightSessionVersion.session_id == str(session_id))
                .order_by(col(LinsightSessionVersion.version).desc())
            )

            return (await session.exec(statement)).all()

    @staticmethod
    async def get_session_version_by_file_id(file_id: str) -> LinsightSessionVersion | None:
        """
        According to DOCUMENTIDGet Ideas Conversation Version
        :param file_id: Doc.ID
        :return: Inspiration Conversation Version Object
        """
        async with get_async_db_session() as session:
            dialect = session.get_bind().dialect.name
            statement = select(LinsightSessionVersion).where(
                json_search_exists(LinsightSessionVersion.files, file_id, dialect)
            )
            result = await session.exec(statement)
            return result.first()

    # Get a list of Ideas session versions based on task status
    @staticmethod
    async def get_session_versions_by_status(status: SessionVersionStatusEnum) -> list[LinsightSessionVersion]:
        """
        Get a list of Ideas session versions based on task status
        :param status: Session Version Status
        :return: Inspiration Session Version List
        """
        async with get_async_db_session() as session:
            statement = select(LinsightSessionVersion).where(LinsightSessionVersion.status == status)
            result = await session.exec(statement)
            return result.all()

    # Bulk Update Ideas Session Version Status
    @staticmethod
    async def batch_update_session_versions_status(
        session_version_ids: list[str], status: SessionVersionStatusEnum, **kwargs
    ) -> None:
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
