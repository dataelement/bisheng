from __future__ import annotations

from sqlmodel import select

from bisheng.approval.domain.models.approval_scenario import (
    ApprovalFlowDefinition,
    ApprovalFlowVersion,
    ApprovalNodeDefinition,
    ApprovalRouteRule,
    ApprovalScenario,
)
from bisheng.core.database import get_async_db_session


class ApprovalScenarioRepository:
    @classmethod
    async def create_scenario(cls, row: ApprovalScenario) -> ApprovalScenario:
        async with get_async_db_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    @classmethod
    async def get_scenario_by_code(cls, tenant_id: int, scenario_code: str) -> ApprovalScenario | None:
        statement = select(ApprovalScenario).where(
            ApprovalScenario.tenant_id == tenant_id,
            ApprovalScenario.scenario_code == scenario_code,
        )
        async with get_async_db_session() as session:
            return (await session.exec(statement)).first()

    @classmethod
    async def get_scenario(cls, scenario_id: int) -> ApprovalScenario | None:
        async with get_async_db_session() as session:
            return await session.get(ApprovalScenario, scenario_id)

    @classmethod
    async def list_scenarios(cls, tenant_id: int) -> list[ApprovalScenario]:
        statement = (
            select(ApprovalScenario)
            .where(ApprovalScenario.tenant_id == tenant_id)
            .order_by(ApprovalScenario.id.desc())
        )
        async with get_async_db_session() as session:
            return list((await session.exec(statement)).all())

    @classmethod
    async def create_route_rule(cls, row: ApprovalRouteRule) -> ApprovalRouteRule:
        async with get_async_db_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    @classmethod
    async def list_route_rules(cls, tenant_id: int, scenario_id: int) -> list[ApprovalRouteRule]:
        statement = (
            select(ApprovalRouteRule)
            .where(
                ApprovalRouteRule.tenant_id == tenant_id,
                ApprovalRouteRule.scenario_id == scenario_id,
            )
            .order_by(ApprovalRouteRule.sort_order.asc(), ApprovalRouteRule.id.asc())
        )
        async with get_async_db_session() as session:
            return list((await session.exec(statement)).all())

    @classmethod
    async def create_flow_definition(cls, row: ApprovalFlowDefinition) -> ApprovalFlowDefinition:
        async with get_async_db_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    @classmethod
    async def create_flow_version(cls, row: ApprovalFlowVersion) -> ApprovalFlowVersion:
        async with get_async_db_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    @classmethod
    async def get_active_flow_version(cls, tenant_id: int, flow_definition_id: int) -> ApprovalFlowVersion | None:
        statement = (
            select(ApprovalFlowVersion)
            .where(
                ApprovalFlowVersion.tenant_id == tenant_id,
                ApprovalFlowVersion.flow_definition_id == flow_definition_id,
                ApprovalFlowVersion.is_active.is_(True),
            )
            .order_by(ApprovalFlowVersion.version_no.desc(), ApprovalFlowVersion.id.desc())
        )
        async with get_async_db_session() as session:
            return (await session.exec(statement)).first()

    @classmethod
    async def create_node_definition(cls, row: ApprovalNodeDefinition) -> ApprovalNodeDefinition:
        async with get_async_db_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    @classmethod
    async def list_node_definitions(cls, tenant_id: int, flow_version_id: int) -> list[ApprovalNodeDefinition]:
        statement = (
            select(ApprovalNodeDefinition)
            .where(
                ApprovalNodeDefinition.tenant_id == tenant_id,
                ApprovalNodeDefinition.flow_version_id == flow_version_id,
            )
            .order_by(ApprovalNodeDefinition.node_order.asc(), ApprovalNodeDefinition.id.asc())
        )
        async with get_async_db_session() as session:
            return list((await session.exec(statement)).all())
