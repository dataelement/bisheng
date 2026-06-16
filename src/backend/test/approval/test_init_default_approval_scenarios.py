from __future__ import annotations

import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_scenario import (
    ApprovalFlowDefinition,
    ApprovalFlowVersion,
    ApprovalNodeDefinition,
    ApprovalRouteRule,
    ApprovalScenario,
)
from bisheng.common.init_data import _DEFAULT_APPROVAL_SCENARIO_SEEDS, _init_default_approval_scenarios
from bisheng.core.context.tenant import DEFAULT_TENANT_ID


@pytest_asyncio.fixture
async def approval_db_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        ApprovalScenario.__table__,
        ApprovalRouteRule.__table__,
        ApprovalFlowDefinition.__table__,
        ApprovalFlowVersion.__table__,
        ApprovalNodeDefinition.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: SQLModel.metadata.create_all(sync_conn, tables=tables))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session(approval_db_engine):
    async with AsyncSession(bind=approval_db_engine, expire_on_commit=False) as s:
        yield s


async def test_seeds_two_scenarios_with_default_branch_and_or_node(session):
    await _init_default_approval_scenarios(session)

    scenarios = (await session.exec(select(ApprovalScenario))).all()
    assert {s.scenario_code for s in scenarios} == {
        "channel_subscribe_request",
        "knowledge_space_subscribe_request",
    }

    for seed in _DEFAULT_APPROVAL_SCENARIO_SEEDS:
        scenario = next(s for s in scenarios if s.scenario_code == seed["scenario_code"])
        assert scenario.tenant_id == DEFAULT_TENANT_ID
        assert scenario.enabled is True

        # One catch-all default branch routed to a flow definition.
        routes = (
            await session.exec(select(ApprovalRouteRule).where(ApprovalRouteRule.scenario_id == scenario.id))
        ).all()
        assert len(routes) == 1
        route = routes[0]
        assert route.route_type == "flow"
        assert route.match_config == {}  # catch-all: any applicant hits the default branch
        assert route.flow_definition_id is not None

        # Active flow version holds a single OR-mode node.
        version = (
            await session.exec(
                select(ApprovalFlowVersion).where(
                    ApprovalFlowVersion.flow_definition_id == route.flow_definition_id,
                    ApprovalFlowVersion.is_active == True,  # noqa: E712
                )
            )
        ).first()
        assert version is not None
        nodes = (
            await session.exec(
                select(ApprovalNodeDefinition).where(ApprovalNodeDefinition.flow_version_id == version.id)
            )
        ).all()
        assert len(nodes) == 1
        node = nodes[0]
        assert node.node_mode == "or"  # 或签
        assert node.approver_config == {"sources": seed["sources"]}


async def test_seeding_is_idempotent(session):
    await _init_default_approval_scenarios(session)
    await _init_default_approval_scenarios(session)

    scenarios = (await session.exec(select(ApprovalScenario))).all()
    routes = (await session.exec(select(ApprovalRouteRule))).all()
    nodes = (await session.exec(select(ApprovalNodeDefinition))).all()

    # Re-running init must not duplicate any seeded rows.
    assert len(scenarios) == len(_DEFAULT_APPROVAL_SCENARIO_SEEDS)
    assert len(routes) == len(_DEFAULT_APPROVAL_SCENARIO_SEEDS)
    assert len(nodes) == len(_DEFAULT_APPROVAL_SCENARIO_SEEDS)
