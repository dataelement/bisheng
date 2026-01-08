from datetime import datetime
from enum import Enum
from typing import List, Optional

from sqlmodel import Field, select, Column, DateTime, text, Text, func, or_, JSON

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_sync_db_session, get_async_db_session
from bisheng.utils import generate_uuid


# System Module Enumeration
class SystemId(Enum):
    CHAT = "chat"  # Sessions
    BUILD = "build"  # Build.
    KNOWLEDGE = "knowledge"  # The knowledge base upon
    SYSTEM = "system"  # System
    DASHBOARD = "dashboard"  # KANBAN


# Action Behavior Enumeration
class EventType(Enum):
    CREATE_CHAT = "create_chat"  # New Session
    DELETE_CHAT = "delete_chat"  # Delete Thread

    CREATE_BUILD = "create_build"  # New App
    UPDATE_BUILD = "update_build"  # Edit App Page
    DELETE_BUILD = "delete_build"  # Delete App?

    CREATE_KNOWLEDGE = "create_knowledge"  # New Knowledge Base
    DELETE_KNOWLEDGE = "delete_knowledge"  # Delete Knowledge Base
    UPLOAD_FILE = "upload_file"  # Knowledge Base Upload Files
    DELETE_FILE = "delete_file"  # Knowledge Base Delete File

    UPDATE_USER = "update_user"  # Edit account
    FORBID_USER = "forbid_user"  # Deactivate user
    RECOVER_USER = "recover_user"  # Enable User
    CREATE_USER_GROUP = "create_user_group"  # Add Usergroup
    DELETE_USER_GROUP = "delete_user_group"  # Can delete existing usergroups
    UPDATE_USER_GROUP = "update_user_group"  # Can edit existing usergroups
    CREATE_ROLE = "create_role"  # Create a Role
    DELETE_ROLE = "delete_role"  # Delete a Role
    UPDATE_ROLE = "update_role"  # Edit a Role

    ADD_TOOL = "add_tool"  # Add Widget
    UPDATE_TOOL = "update_tool"
    DELETE_TOOL = "delete_tool"

    USER_LOGIN = "user_login"  # Login Pengguna

    CREATE_DASHBOARD = "create_dashboard"
    UPDATE_DASHBOARD = "update_dashboard"
    DELETE_DASHBOARD = "delete_dashboard"


# Action object type enumeration
class ObjectType(Enum):
    NONE = "none"  # W/O
    FLOW = "flow"  # Skill
    WORK_FLOW = "work_flow"  # The Workflow
    ASSISTANT = "assistant"  # assistant
    KNOWLEDGE = "knowledge"  # The knowledge base upon
    FILE = "file"  # Doc.
    USER_CONF = "user_conf"  # User Configuration
    USER_GROUP_CONF = "user_group_conf"  # User Group Configuration
    ROLE_CONF = "role_conf"  # Configuration of user roles
    TOOL = "tool"
    DASHBOARD = "dashboard"  # KANBAN


class AuditLogBase(SQLModelSerializable):
    """
    Audit Log Table
    """
    operator_id: int = Field(index=True, description="Operating User'sID")
    operator_name: Optional[str] = Field(description="Username")
    group_ids: Optional[List[int | str]] = Field(sa_column=Column(JSON), description="Belongs to a user groupIDVertical")
    system_id: Optional[str] = Field(index=True, description="Module Item")
    event_type: Optional[str] = Field(index=True, description="Operation behaviors")
    object_type: Optional[str] = Field(index=True, description="Action object type")
    object_id: Optional[str] = Field(index=True, description="Operation ObjectID")
    object_name: Optional[str] = Field(sa_column=Column(Text), description="Action object name")
    note: Optional[str] = Field(sa_column=Column(Text), description="Action notes")
    ip_address: Optional[str] = Field(index=True, description="Client's at time of operationIP<g id='Bold'>Address:</g>")
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')), description="operate time")
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class AuditLog(AuditLogBase, table=True):
    # id = 2 Represents the default user group
    id: str = Field(default_factory=generate_uuid, primary_key=True, index=True, description="primary keyuuidFormat")


class AuditLogDao(AuditLogBase):

    @classmethod
    def get_audit_logs(cls, group_ids: List[int], operator_ids: List[int] = 0, start_time: datetime = None,
                       end_time: datetime = None, system_id: str = None, event_type: str = None,
                       page: int = 0, limit: int = 0) -> (List[AuditLog], int):
        """
        Filter logs by user group
        """
        statement = select(AuditLog)
        count_statement = select(func.count(AuditLog.id))
        if group_ids:
            group_filters = []
            for one in group_ids:
                group_filters.append(func.json_contains(AuditLog.group_ids, str(one)))
            statement = statement.where(or_(*group_filters))
            count_statement = count_statement.where(or_(*group_filters))
        if operator_ids:
            statement = statement.where(AuditLog.operator_id.in_(operator_ids))
            count_statement = count_statement.where(AuditLog.operator_id.in_(operator_ids))
        if start_time:
            statement = statement.where(AuditLog.create_time >= start_time)
            count_statement = count_statement.where(AuditLog.create_time >= start_time)
        if end_time:
            statement = statement.where(AuditLog.create_time <= end_time)
            count_statement = count_statement.where(AuditLog.create_time <= end_time)
        if system_id:
            statement = statement.where(AuditLog.system_id == system_id)
            count_statement = count_statement.where(AuditLog.system_id == system_id)
        if event_type:
            statement = statement.where(AuditLog.event_type == event_type)
            count_statement = count_statement.where(AuditLog.event_type == event_type)
        if page and limit:
            statement = statement.offset((page - 1) * limit).limit(limit).order_by(AuditLog.create_time.desc())
        with get_sync_db_session() as session:
            return session.exec(statement).all(), session.scalar(count_statement)

    @classmethod
    def insert_audit_logs(cls, audit_logs: List[AuditLog]):
        with get_sync_db_session() as session:
            session.add_all(audit_logs)
            session.commit()

    @classmethod
    async def ainsert_audit_logs(cls, audit_logs: List[AuditLog]):
        async with get_async_db_session() as session:
            session.add_all(audit_logs)
            await session.commit()

    @classmethod
    def get_all_operators(cls, group_ids: List[int]):
        statement = select(AuditLog.operator_id, AuditLog.operator_name).distinct()
        if group_ids:
            group_filters = []
            for one in group_ids:
                group_filters.append(func.json_contains(AuditLog.group_ids, str(one)))
            statement = statement.where(or_(*group_filters))

        with get_sync_db_session() as session:
            return session.exec(statement).all()
