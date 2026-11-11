"""F119 专用的隔离 SQL 夹具。不自动作用于旧测试。"""

from contextlib import contextmanager
from copy import deepcopy

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlmodel import Session

from bisheng.database.models.flow import Flow
from bisheng.database.models.flow_version import FlowVersion
from bisheng.workflow.domain.models.platform_agent_execution import PlatformAgentExecution
from bisheng.workflow.domain.repositories.platform_agent import PlatformAgentRepository


@pytest.fixture
def agent_store(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with _agent_store(monkeypatch, engine) as store:
        yield store


@pytest.fixture
def long_agent_store(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'long-agent.sqlite3'}")
    with _agent_store(monkeypatch, engine) as store:
        yield store


@contextmanager
def _agent_store(monkeypatch, engine):
    from unittest.mock import AsyncMock

    from bisheng.workflow.domain.services import platform_agent_service as domain

    monkeypatch.setattr(
        domain,
        "read_current_person_facts",
        AsyncMock(
            side_effect=lambda ids: {ident: {"state": "active", "tenant_id": 7, "token_version": 0} for ident in ids}
        ),
    )
    for table in (Flow.__table__, FlowVersion.__table__, PlatformAgentExecution.__table__):
        table.create(engine)
    sessions = sessionmaker(engine, class_=Session, expire_on_commit=False)
    graph = {"nodes": [], "edges": []}
    with sessions() as session:
        session.add(Flow(id="f" * 32, name="fixture", user_id=11, tenant_id=7, data=deepcopy(graph)))
        session.add(
            FlowVersion(id=1, flow_id="f" * 32, name="v1", user_id=11, tenant_id=7, data=deepcopy(graph), is_current=1)
        )
        session.commit()
    now = [1000.0]
    repository = PlatformAgentRepository(sessions, clock=lambda: now[0])
    try:
        yield repository, sessions, graph, now
    finally:
        engine.dispose()


@pytest.fixture
def registration_store():
    from bisheng.core.context.tenant import strict_tenant_filter, tenant_execution_scope

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    # 夹具中的业务主体属于租户 7, 不依赖过滤器尚未注册才能读取。
    with tenant_execution_scope(7), strict_tenant_filter(), _registration_store(engine) as repository:
        yield repository


@pytest.fixture
def invocation_registration_store(tmp_path):
    from bisheng.workflow.domain.models.kunlian_workflow_run import KunlianWorkflowRun

    engine = create_engine(f"sqlite:///{tmp_path / 'invocation.sqlite3'}")
    with _registration_store(engine, (KunlianWorkflowRun,)) as repository:
        yield repository


@contextmanager
def _registration_store(engine, additional_models=()):
    from bisheng.workflow.domain.models.kunlian_registration import (
        KunlianWorkflowChange,
        KunlianWorkflowCreation,
        KunlianWorkflowStream,
        KunlianWorkflowVersion,
    )
    from bisheng.workflow.domain.repositories.kunlian_registration import RegistrationRepository

    for model in (
        Flow,
        FlowVersion,
        KunlianWorkflowCreation,
        KunlianWorkflowStream,
        KunlianWorkflowVersion,
        KunlianWorkflowChange,
        *additional_models,
    ):
        model.__table__.create(engine)

    @contextmanager
    def sessions():
        with Session(engine, expire_on_commit=False) as session:
            yield session

    try:
        yield RegistrationRepository(sessions)
    finally:
        engine.dispose()
