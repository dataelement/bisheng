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


async def _delete_row(session, model_cls, row_id: int) -> bool:
    row = await session.get(model_cls, row_id)
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    return True


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
    async def update_scenario(cls, row: ApprovalScenario) -> ApprovalScenario:
        async with get_async_db_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    @classmethod
    async def delete_scenario(cls, scenario_id: int) -> bool:
        async with get_async_db_session() as session:
            return await _delete_row(session, ApprovalScenario, scenario_id)

    @classmethod
    async def create_route_rule(cls, row: ApprovalRouteRule) -> ApprovalRouteRule:
        async with get_async_db_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    @classmethod
    async def get_route_rule(cls, route_rule_id: int) -> ApprovalRouteRule | None:
        async with get_async_db_session() as session:
            return await session.get(ApprovalRouteRule, route_rule_id)

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
    async def update_route_rule(cls, row: ApprovalRouteRule) -> ApprovalRouteRule:
        async with get_async_db_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    @classmethod
    async def delete_route_rule(cls, route_rule_id: int) -> bool:
        async with get_async_db_session() as session:
            return await _delete_row(session, ApprovalRouteRule, route_rule_id)

    @classmethod
    async def list_route_rules_by_flow_definition(
        cls, tenant_id: int, flow_definition_id: int
    ) -> list[ApprovalRouteRule]:
        statement = select(ApprovalRouteRule).where(
            ApprovalRouteRule.tenant_id == tenant_id,
            ApprovalRouteRule.flow_definition_id == flow_definition_id,
        )
        async with get_async_db_session() as session:
            return list((await session.exec(statement)).all())

    @classmethod
    async def bulk_update_route_sort_order(cls, ordered_route_ids: list[int]) -> None:
        async with get_async_db_session() as session:
            for index, route_id in enumerate(ordered_route_ids):
                row = await session.get(ApprovalRouteRule, route_id)
                if row is not None:
                    row.sort_order = index
                    session.add(row)
            await session.commit()

    @classmethod
    async def create_flow_definition(cls, row: ApprovalFlowDefinition) -> ApprovalFlowDefinition:
        async with get_async_db_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    @classmethod
    async def get_flow_definition(cls, flow_definition_id: int) -> ApprovalFlowDefinition | None:
        async with get_async_db_session() as session:
            return await session.get(ApprovalFlowDefinition, flow_definition_id)

    @classmethod
    async def list_flow_definitions(cls, tenant_id: int, scenario_id: int) -> list[ApprovalFlowDefinition]:
        statement = (
            select(ApprovalFlowDefinition)
            .where(
                ApprovalFlowDefinition.tenant_id == tenant_id,
                ApprovalFlowDefinition.scenario_id == scenario_id,
            )
            .order_by(ApprovalFlowDefinition.id.desc())
        )
        async with get_async_db_session() as session:
            return list((await session.exec(statement)).all())

    @classmethod
    async def update_flow_definition(cls, row: ApprovalFlowDefinition) -> ApprovalFlowDefinition:
        async with get_async_db_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    @classmethod
    async def delete_flow_definition(cls, flow_definition_id: int) -> bool:
        async with get_async_db_session() as session:
            return await _delete_row(session, ApprovalFlowDefinition, flow_definition_id)

    @classmethod
    async def get_flow_version(cls, flow_version_id: int) -> ApprovalFlowVersion | None:
        async with get_async_db_session() as session:
            return await session.get(ApprovalFlowVersion, flow_version_id)

    @classmethod
    async def create_flow_version(cls, row: ApprovalFlowVersion) -> ApprovalFlowVersion:
        async with get_async_db_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    @classmethod
    async def update_flow_version(cls, row: ApprovalFlowVersion) -> ApprovalFlowVersion:
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
    async def get_node_definition(cls, node_definition_id: int) -> ApprovalNodeDefinition | None:
        async with get_async_db_session() as session:
            return await session.get(ApprovalNodeDefinition, node_definition_id)

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

    @classmethod
    async def update_node_definition(cls, row: ApprovalNodeDefinition) -> ApprovalNodeDefinition:
        async with get_async_db_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    @classmethod
    async def delete_node_definition(cls, node_definition_id: int) -> bool:
        async with get_async_db_session() as session:
            return await _delete_row(session, ApprovalNodeDefinition, node_definition_id)

    @classmethod
    async def delete_nodes_by_flow_version(cls, flow_version_id: int) -> None:
        statement = select(ApprovalNodeDefinition).where(
            ApprovalNodeDefinition.flow_version_id == flow_version_id
        )
        async with get_async_db_session() as session:
            rows = list((await session.exec(statement)).all())
            for row in rows:
                await session.delete(row)
            await session.commit()
