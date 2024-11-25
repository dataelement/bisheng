from datetime import datetime
from enum import Enum
from typing import List, Optional

from bisheng.database.base import session_getter, generate_uuid
from bisheng.database.models.base import SQLModelSerializable
from sqlalchemy import Column, DateTime, delete, text, update, Text, func, or_, JSON
from sqlmodel import Field, select


# 系统模块枚举
class SystemId(Enum):
    CHAT = "chat"  # 会话
    BUILD = "build"  # 构建
    KNOWLEDGE = "knowledge"  # 知识库
    SYSTEM = "system"  # 系统


# 操作行为枚举
class EventType(Enum):
    CREATE_CHAT = "create_chat"  # 新建会话
    DELETE_CHAT = "delete_chat"  # 删除会话

    CREATE_BUILD = "create_build"  # 新建应用
    UPDATE_BUILD = "update_build"  # 编辑应用
    DELETE_BUILD = "delete_build"  # 删除应用

    CREATE_KNOWLEDGE = "create_knowledge"  # 新建知识库
    DELETE_KNOWLEDGE = "delete_knowledge"  # 删除知识库
    UPLOAD_FILE = "upload_file"  # 知识库上传文件
    DELETE_FILE = "delete_file"  # 知识库删除文件

    UPDATE_USER = "update_user"  # 用户编辑
    FORBID_USER = "forbid_user"  # 停用用户
    RECOVER_USER = "recover_user"  # 启用用户
    CREATE_USER_GROUP = "create_user_group"  # 新建用户组
    DELETE_USER_GROUP = "delete_user_group"  # 删除用户组
    UPDATE_USER_GROUP = "update_user_group"  # 编辑用户组
    CREATE_ROLE = "create_role"  # 新建角色
    DELETE_ROLE = "delete_role"  # 删除角色
    UPDATE_ROLE = "update_role"  # 编辑角色

    USER_LOGIN = "user_login" # 用户登录


# 操作对象类型枚举
class ObjectType(Enum):
    NONE = "none"  # 无
    FLOW = "flow"  # 技能
    WORK_FLOW= "work_flow"  # 技能
    ASSISTANT = "assistant"  # 助手
    KNOWLEDGE = "knowledge"  # 知识库
    FILE = "file"  # 文件
    USER_CONF = "user_conf"  # 用户配置
    USER_GROUP_CONF = "user_group_conf"  # 用户组配置
    ROLE_CONF = "role_conf"  # 角色配置


class AuditLogBase(SQLModelSerializable):
    """
    审计日志表
    """
    operator_id: int = Field(index=True, description="操作用户的ID")
    operator_name: Optional[str] = Field(description="用户名")
    group_ids: Optional[List[int]] = Field(sa_column=Column(JSON), description="所属用户组的ID列表")
    system_id: Optional[str] = Field(index=True, description="系统模块")
    event_type: Optional[str] = Field(index=True, description="操作行为")
    object_type: Optional[str] = Field(index=True, description="操作对象类型")
    object_id: Optional[int] = Field(index=True, description="操作对象ID")
    object_name: Optional[str] = Field(sa_column=Column(Text), description="操作对象名称")
    note: Optional[str] = Field(sa_column=Column(Text), description="操作备注")
    ip_address: Optional[str] = Field(index=True, description="操作时客户端的IP地址")
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')), description="操作时间")
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')), description="操作时间")


class AuditLog(AuditLogBase, table=True):
    # id = 2 表示默认用户组
    id: str = Field(default_factory=generate_uuid, primary_key=True, index=True, description="主键，uuid格式")


class AuditLogDao(AuditLogBase):

    @classmethod
    def get_audit_logs(cls, group_ids: List[int], operator_ids: List[int] = 0, start_time: datetime = None,
                       end_time: datetime = None, system_id: str = None, event_type: str = None,
                       page: int = 0, limit: int = 0) -> (List[AuditLog], int):
        """
        通过用户组来筛选日志
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
        with session_getter() as session:
            return session.exec(statement).all(), session.scalar(count_statement)

    @classmethod
    def insert_audit_logs(cls, audit_logs: List[AuditLog]):
        with session_getter() as session:
            session.add_all(audit_logs)
            session.commit()

    @classmethod
    def get_all_operators(cls, group_ids: List[int]):
        statement = select(AuditLog.operator_id, AuditLog.operator_name).distinct()
        if group_ids:
            group_filters = []
            for one in group_ids:
                group_filters.append(func.json_contains(AuditLog.group_ids, str(one)))
            statement = statement.where(or_(*group_filters))

        with session_getter() as session:
            return session.exec(statement).all()
