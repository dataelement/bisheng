from ast import Dict
from datetime import datetime
from typing import Dict, List, Optional

from bisheng.database.base import session_getter, generate_uuid
from bisheng.database.models.base import SQLModelSerializable
from sqlalchemy import Column, DateTime, delete, text, update, Text, func, or_
from sqlmodel import Field, select


class AuditLogBase(SQLModelSerializable):
    """
    审计日志表
    """
    operator_id: int = Field(index=True, description="操作用户的ID")
    operator_name: Optional[str] = Field(index=True, description="用户名")
    group_ids: Optional[List[int]] = Field(index=True, description="所属用户组的ID列表")
    system_id: Optional[str] = Field(index=True, description="系统模块")
    event_type: Optional[str] = Field(index=True, description="操作行为")
    object_type: Optional[str] = Field(index=True, description="操作对象类型")
    object_id: Optional[int] = Field(index=True, description="操作对象ID")
    object_name: Optional[str] = Field(index=True, description="操作对象名称")
    note: Optional[str] = Field(sa_column=Column(Text(255)), description="操作备注")
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
    def get_audit_logs(cls, group_ids: List[int], operator_id: int = 0, start_time: datetime = None,
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
                group_filters.append(func.json_array_contains(AuditLog.group_ids, one))
            statement = statement.where(or_(*group_filters))
            count_statement = count_statement.where(or_(*group_filters))
        if operator_id:
            statement = statement.where(AuditLog.operator_id == operator_id)
            count_statement = count_statement.where(AuditLog.operator_id == operator_id)
        if start_time and end_time:
            statement = statement.where(AuditLog.create_time >= start_time).where(AuditLog.create_time <= end_time)
            count_statement = count_statement.where(AuditLog.create_time >= start_time).where(
                AuditLog.create_time <= end_time)
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
