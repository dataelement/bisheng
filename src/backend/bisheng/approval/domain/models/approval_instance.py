from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, Index, Integer, String, Text, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import JsonType, UPDATE_TIME_SERVER_DEFAULT


class ApprovalInstanceStatus:
    PENDING = 'pending'
    APPROVED = 'approved'
    EXECUTING = 'executing'
    EXECUTED = 'executed'
    REJECTED = 'rejected'
    EXCEPTION = 'exception'
    WITHDRAWN = 'withdrawn'
    CANCELLED = 'cancelled'
    EXECUTE_FAILED = 'execute_failed'


class ApprovalTaskStatus:
    PENDING = 'pending'
    APPROVED = 'approved'
    REJECTED = 'rejected'
    SKIPPED = 'skipped'
    CANCELLED = 'cancelled'


class ApprovalExceptionType:
    ROUTE_MISSING = 'route_missing'
    APPROVER_EMPTY = 'approver_empty'
    EXECUTE_FAILED = 'execute_failed'


class ApprovalOutboxStatus:
    PENDING = 'pending'
    SUCCESS = 'success'
    FAILED = 'failed'


class ApprovalInstanceBase(SQLModelSerializable):
    tenant_id: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=False, index=True))
    scenario_code: str = Field(sa_column=Column(String(64), nullable=False, index=True))
    scenario_name: str = Field(sa_column=Column(String(255), nullable=False))
    handler_key: str = Field(sa_column=Column(String(128), nullable=False))
    business_key: str = Field(sa_column=Column(String(255), nullable=False, index=True))
    business_resource_type: str = Field(sa_column=Column(String(64), nullable=False))
    business_resource_id: str = Field(sa_column=Column(String(128), nullable=False))
    business_name: str = Field(sa_column=Column(String(255), nullable=False))
    applicant_user_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    applicant_user_name: str = Field(sa_column=Column(String(255), nullable=False))
    applicant_department_id: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True, index=True))
    flow_version_id: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True, index=True))
    route_rule_id: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True, index=True))
    status: str = Field(sa_column=Column(String(32), nullable=False, index=True))
    reason: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    payload_snapshot: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    detail_snapshot: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    current_node_name: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    latest_approver_user_id: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True, index=True))
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT))


class ApprovalInstance(ApprovalInstanceBase, table=True):
    __tablename__ = 'approval_instance'
    __table_args__ = (
        Index(
            'idx_approval_instance_dedupe_lookup',
            'tenant_id',
            'scenario_code',
            'business_key',
            'applicant_user_id',
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)


class ApprovalTaskBase(SQLModelSerializable):
    tenant_id: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=False, index=True))
    instance_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    flow_version_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    node_code: str = Field(sa_column=Column(String(64), nullable=False))
    node_name: str = Field(sa_column=Column(String(255), nullable=False))
    node_order: int = Field(default=0, sa_column=Column(Integer, nullable=False, index=True))
    approver_user_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    approver_source_type: str = Field(sa_column=Column(String(64), nullable=False))
    node_mode: str = Field(sa_column=Column(String(16), nullable=False))
    status: str = Field(sa_column=Column(String(32), nullable=False, index=True))
    comment: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    acted_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT))


class ApprovalTask(ApprovalTaskBase, table=True):
    __tablename__ = 'approval_task'

    id: Optional[int] = Field(default=None, primary_key=True)


class ApprovalExceptionBase(SQLModelSerializable):
    tenant_id: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=False, index=True))
    instance_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    exception_type: str = Field(sa_column=Column(String(64), nullable=False, index=True))
    status: str = Field(default='open', sa_column=Column(String(32), nullable=False, index=True))
    detail: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    resolved_action: Optional[str] = Field(default=None, sa_column=Column(String(64), nullable=True))
    resolved_by_user_id: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True, index=True))
    resolved_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT))


class ApprovalException(ApprovalExceptionBase, table=True):
    __tablename__ = 'approval_exception'

    id: Optional[int] = Field(default=None, primary_key=True)


class ApprovalOutboxBase(SQLModelSerializable):
    tenant_id: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=False, index=True))
    instance_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    handler_key: str = Field(sa_column=Column(String(128), nullable=False))
    status: str = Field(default=ApprovalOutboxStatus.PENDING, sa_column=Column(String(32), nullable=False, index=True))
    retry_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text('0')))
    payload_snapshot: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    error_summary: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT))


class ApprovalOutbox(ApprovalOutboxBase, table=True):
    __tablename__ = 'approval_outbox'

    id: Optional[int] = Field(default=None, primary_key=True)


class ApprovalActionLogBase(SQLModelSerializable):
    tenant_id: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=False, index=True))
    instance_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    action: str = Field(sa_column=Column(String(64), nullable=False, index=True))
    operator_user_id: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True, index=True))
    operator_user_name: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    detail: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT))


class ApprovalActionLog(ApprovalActionLogBase, table=True):
    __tablename__ = 'approval_action_log'

    id: Optional[int] = Field(default=None, primary_key=True)
