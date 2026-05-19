from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import JsonType, UPDATE_TIME_SERVER_DEFAULT


class ApprovalScenarioBase(SQLModelSerializable):
    tenant_id: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=False, index=True))
    scenario_code: str = Field(sa_column=Column(String(64), nullable=False))
    scenario_name: str = Field(sa_column=Column(String(255), nullable=False))
    enabled: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, server_default=text('0')))
    display_name: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT))


class ApprovalScenario(ApprovalScenarioBase, table=True):
    __tablename__ = 'approval_scenario'
    __table_args__ = (UniqueConstraint('tenant_id', 'scenario_code', name='uq_approval_scenario_tenant_code'),)

    id: Optional[int] = Field(default=None, primary_key=True)


class ApprovalRouteRuleBase(SQLModelSerializable):
    tenant_id: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=False, index=True))
    scenario_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    route_name: str = Field(sa_column=Column(String(255), nullable=False))
    route_type: str = Field(sa_column=Column(String(32), nullable=False, index=True))
    sort_order: int = Field(default=0, sa_column=Column(Integer, nullable=False, index=True))
    flow_definition_id: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True, index=True))
    match_config: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT))


class ApprovalRouteRule(ApprovalRouteRuleBase, table=True):
    __tablename__ = 'approval_route_rule'

    id: Optional[int] = Field(default=None, primary_key=True)


class ApprovalFlowDefinitionBase(SQLModelSerializable):
    tenant_id: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=False, index=True))
    scenario_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    flow_code: str = Field(sa_column=Column(String(64), nullable=False))
    flow_name: str = Field(sa_column=Column(String(255), nullable=False))
    is_active: bool = Field(default=True, sa_column=Column(Boolean, nullable=False, server_default=text('1')))
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT))


class ApprovalFlowDefinition(ApprovalFlowDefinitionBase, table=True):
    __tablename__ = 'approval_flow_definition'
    __table_args__ = (UniqueConstraint('tenant_id', 'flow_code', name='uq_approval_flow_definition_tenant_code'),)

    id: Optional[int] = Field(default=None, primary_key=True)


class ApprovalFlowVersionBase(SQLModelSerializable):
    tenant_id: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=False, index=True))
    flow_definition_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    version_no: int = Field(default=1, sa_column=Column(Integer, nullable=False))
    is_active: bool = Field(default=True, sa_column=Column(Boolean, nullable=False, server_default=text('1')))
    definition_snapshot: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT))


class ApprovalFlowVersion(ApprovalFlowVersionBase, table=True):
    __tablename__ = 'approval_flow_version'
    __table_args__ = (UniqueConstraint('flow_definition_id', 'version_no', name='uq_approval_flow_version_no'),)

    id: Optional[int] = Field(default=None, primary_key=True)


class ApprovalNodeDefinitionBase(SQLModelSerializable):
    tenant_id: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=False, index=True))
    flow_version_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    node_code: str = Field(sa_column=Column(String(64), nullable=False))
    node_name: str = Field(sa_column=Column(String(255), nullable=False))
    node_order: int = Field(default=0, sa_column=Column(Integer, nullable=False, index=True))
    node_mode: str = Field(sa_column=Column(String(16), nullable=False))
    approver_config: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    extra_config: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT))


class ApprovalNodeDefinition(ApprovalNodeDefinitionBase, table=True):
    __tablename__ = 'approval_node_definition'
    __table_args__ = (UniqueConstraint('flow_version_id', 'node_code', name='uq_approval_node_definition_code'),)

    id: Optional[int] = Field(default=None, primary_key=True)
