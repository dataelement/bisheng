from __future__ import annotations

from sqlmodel import select

from bisheng.approval.domain.models.approval_instance import ApprovalInstance
from bisheng.approval.domain.models.approval_scenario import (
    ApprovalFlowDefinition,
    ApprovalFlowVersion,
    ApprovalNodeDefinition,
    ApprovalRouteRule,
    ApprovalScenario,
)
from bisheng.common.errcode.approval import (
    ApprovalConditionOptionInvalidError,
    ApprovalConfigInUseError,
)
from bisheng.core.database import get_async_db_session


async def _lock_ordered_routes(
    session,
    *,
    tenant_id: int,
    scenario_id: int | None = None,
    flow_definition_id: int | None = None,
) -> list[ApprovalRouteRule]:
    statement = select(ApprovalRouteRule).where(
        ApprovalRouteRule.tenant_id == tenant_id
    )
    if scenario_id is not None:
        statement = statement.where(
            ApprovalRouteRule.scenario_id == scenario_id
        )
    if flow_definition_id is not None:
        statement = statement.where(
            ApprovalRouteRule.flow_definition_id == flow_definition_id
        )
    statement = statement.order_by(
        ApprovalRouteRule.sort_order.asc(),
        ApprovalRouteRule.id.asc(),
    ).with_for_update()
    return list((await session.exec(statement)).all())


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
    async def get_scenario_by_code(
        cls,
        tenant_id: int,
        scenario_code: str,
        *,
        session=None,
        for_update: bool = False,
    ) -> ApprovalScenario | None:
        statement = select(ApprovalScenario).where(
            ApprovalScenario.tenant_id == tenant_id,
            ApprovalScenario.scenario_code == scenario_code,
        )
        if for_update:
            statement = statement.with_for_update()
        if session is not None:
            return (await session.exec(statement)).first()
        async with get_async_db_session() as session:
            return (await session.exec(statement)).first()

    @classmethod
    async def get_scenario(
        cls,
        scenario_id: int,
        *,
        session=None,
        for_update: bool = False,
    ) -> ApprovalScenario | None:
        if session is not None:
            statement = select(ApprovalScenario).where(
                ApprovalScenario.id == scenario_id
            )
            if for_update:
                statement = statement.with_for_update()
            return (await session.exec(statement)).first()
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
    async def create_route_rule_safely(
        cls,
        row: ApprovalRouteRule,
    ) -> ApprovalRouteRule:
        async with get_async_db_session() as session:
            try:
                await _lock_ordered_routes(
                    session,
                    tenant_id=int(row.tenant_id),
                    scenario_id=int(row.scenario_id),
                )
                if row.flow_definition_id is not None:
                    flow = (
                        await session.exec(
                            select(ApprovalFlowDefinition)
                            .where(
                                ApprovalFlowDefinition.id
                                == row.flow_definition_id,
                                ApprovalFlowDefinition.tenant_id
                                == row.tenant_id,
                                ApprovalFlowDefinition.scenario_id
                                == row.scenario_id,
                            )
                            .with_for_update()
                        )
                    ).first()
                    if flow is None or not flow.is_active:
                        raise ApprovalConditionOptionInvalidError()
                session.add(row)
                await session.commit()
                await session.refresh(row)
                return row
            except Exception:
                await session.rollback()
                raise

    @classmethod
    async def get_route_rule(
        cls,
        route_rule_id: int,
        *,
        session=None,
        for_update: bool = False,
    ) -> ApprovalRouteRule | None:
        if session is not None:
            statement = select(ApprovalRouteRule).where(
                ApprovalRouteRule.id == route_rule_id
            )
            if for_update:
                statement = statement.with_for_update()
            return (await session.exec(statement)).first()
        async with get_async_db_session() as session:
            return await session.get(ApprovalRouteRule, route_rule_id)

    @classmethod
    async def list_route_rules(
        cls,
        tenant_id: int,
        scenario_id: int,
        *,
        session=None,
        for_update: bool = False,
        enabled_only: bool = False,
    ) -> list[ApprovalRouteRule]:
        statement = (
            select(ApprovalRouteRule)
            .where(
                ApprovalRouteRule.tenant_id == tenant_id,
                ApprovalRouteRule.scenario_id == scenario_id,
            )
            .order_by(ApprovalRouteRule.sort_order.asc(), ApprovalRouteRule.id.asc())
        )
        if enabled_only:
            statement = statement.where(
                (ApprovalRouteRule.enabled == True)  # noqa: E712
            )
        if for_update:
            statement = statement.with_for_update()
        if session is not None:
            return list((await session.exec(statement)).all())
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
    async def update_route_rule_safely(
        cls,
        *,
        tenant_id: int,
        route_rule_id: int,
        payload: dict,
    ) -> ApprovalRouteRule:
        async with get_async_db_session() as session:
            try:
                row = (
                    await session.exec(
                        select(ApprovalRouteRule)
                        .where(
                            ApprovalRouteRule.id == route_rule_id,
                            ApprovalRouteRule.tenant_id == tenant_id,
                        )
                        .with_for_update()
                    )
                ).first()
                if row is None:
                    raise ValueError(f"route not found: {route_rule_id}")

                route_type = str(
                    payload.get("route_type", row.route_type) or ""
                )
                flow_definition_id = payload.get(
                    "flow_definition_id",
                    row.flow_definition_id,
                )
                if route_type == "pass":
                    flow_definition_id = None
                elif (
                    route_type not in {"flow", "approval"}
                    or flow_definition_id is None
                ):
                    raise ApprovalConditionOptionInvalidError()
                else:
                    flow = (
                        await session.exec(
                            select(ApprovalFlowDefinition)
                            .where(
                                ApprovalFlowDefinition.id
                                == flow_definition_id,
                                ApprovalFlowDefinition.tenant_id
                                == tenant_id,
                                ApprovalFlowDefinition.scenario_id
                                == row.scenario_id,
                            )
                            .with_for_update()
                        )
                    ).first()
                    if flow is None or not flow.is_active:
                        raise ApprovalConditionOptionInvalidError()

                if payload.get("route_name"):
                    row.route_name = payload["route_name"]
                if payload.get("route_type"):
                    row.route_type = route_type
                if "sort_order" in payload:
                    row.sort_order = int(payload["sort_order"])
                if (
                    "flow_definition_id" in payload
                    or route_type == "pass"
                ):
                    row.flow_definition_id = flow_definition_id
                if "match_config" in payload:
                    row.match_config = payload["match_config"] or {}
                if "enabled" in payload:
                    row.enabled = bool(payload["enabled"])
                session.add(row)
                await session.commit()
                await session.refresh(row)
                return row
            except Exception:
                await session.rollback()
                raise

    @classmethod
    async def delete_route_rule(cls, route_rule_id: int) -> bool:
        async with get_async_db_session() as session:
            return await _delete_row(session, ApprovalRouteRule, route_rule_id)

    @classmethod
    async def delete_route_rule_safely(
        cls,
        *,
        tenant_id: int,
        route_rule_id: int,
    ) -> bool:
        async with get_async_db_session() as session:
            try:
                route = (
                    await session.exec(
                        select(ApprovalRouteRule)
                        .where(
                            ApprovalRouteRule.id == route_rule_id,
                            ApprovalRouteRule.tenant_id == tenant_id,
                        )
                        .with_for_update()
                    )
                ).first()
                if route is None:
                    return False
                referenced = (
                    await session.exec(
                        select(ApprovalInstance.id)
                        .where(ApprovalInstance.route_rule_id == route_rule_id)
                        .limit(1)
                        .with_for_update()
                    )
                ).first()
                if referenced is not None:
                    raise ApprovalConfigInUseError()
                await session.delete(route)
                await session.commit()
                return True
            except Exception:
                await session.rollback()
                raise

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
    async def bulk_update_route_sort_order_safely(
        cls,
        *,
        tenant_id: int,
        scenario_id: int,
        ordered_route_ids: list[int],
    ) -> None:
        async with get_async_db_session() as session:
            try:
                rows = await _lock_ordered_routes(
                    session,
                    tenant_id=tenant_id,
                    scenario_id=scenario_id,
                )
                row_map = {
                    int(row.id): row
                    for row in rows
                    if row.id is not None
                }
                if set(ordered_route_ids) != set(row_map):
                    raise ValueError(
                        "route order does not match scenario routes"
                    )
                for index, route_id in enumerate(ordered_route_ids):
                    row = row_map[int(route_id)]
                    row.sort_order = index
                    session.add(row)
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    @classmethod
    async def create_flow_definition(cls, row: ApprovalFlowDefinition) -> ApprovalFlowDefinition:
        async with get_async_db_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    @classmethod
    async def get_flow_definition(
        cls,
        flow_definition_id: int,
        *,
        session=None,
        for_update: bool = False,
    ) -> ApprovalFlowDefinition | None:
        if session is not None:
            statement = select(ApprovalFlowDefinition).where(
                ApprovalFlowDefinition.id == flow_definition_id
            )
            if for_update:
                statement = statement.with_for_update()
            return (await session.exec(statement)).first()
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
    async def update_flow_definition_safely(
        cls,
        *,
        tenant_id: int,
        flow_definition_id: int,
        payload: dict,
    ) -> ApprovalFlowDefinition:
        async with get_async_db_session() as session:
            try:
                await _lock_ordered_routes(
                    session,
                    tenant_id=tenant_id,
                    flow_definition_id=flow_definition_id,
                )
                row = (
                    await session.exec(
                        select(ApprovalFlowDefinition)
                        .where(
                            ApprovalFlowDefinition.id
                            == flow_definition_id,
                            ApprovalFlowDefinition.tenant_id == tenant_id,
                        )
                        .with_for_update()
                    )
                ).first()
                if row is None:
                    raise ValueError(
                        f"flow not found: {flow_definition_id}"
                    )
                if payload.get("flow_name"):
                    row.flow_name = payload["flow_name"]
                if "is_active" in payload:
                    row.is_active = bool(payload["is_active"])
                session.add(row)
                await session.commit()
                await session.refresh(row)
                return row
            except Exception:
                await session.rollback()
                raise

    @classmethod
    async def delete_flow_definition(cls, flow_definition_id: int) -> bool:
        async with get_async_db_session() as session:
            return await _delete_row(session, ApprovalFlowDefinition, flow_definition_id)

    @classmethod
    async def delete_flow_definition_safely(
        cls,
        *,
        tenant_id: int,
        flow_definition_id: int,
    ) -> bool:
        async with get_async_db_session() as session:
            try:
                # 与申请路径保持 route → flow → version 的锁顺序, 避免并发删除
                # 在实例提交后留下悬空 route/flow_version 引用。
                bound_routes = await _lock_ordered_routes(
                    session,
                    tenant_id=tenant_id,
                    flow_definition_id=flow_definition_id,
                )
                if bound_routes:
                    raise ApprovalConfigInUseError()

                flow = (
                    await session.exec(
                        select(ApprovalFlowDefinition)
                        .where(
                            ApprovalFlowDefinition.id == flow_definition_id,
                            ApprovalFlowDefinition.tenant_id == tenant_id,
                        )
                        .with_for_update()
                    )
                ).first()
                if flow is None:
                    return False

                versions = list(
                    (
                        await session.exec(
                            select(ApprovalFlowVersion)
                            .where(
                                ApprovalFlowVersion.tenant_id == tenant_id,
                                ApprovalFlowVersion.flow_definition_id
                                == flow_definition_id,
                            )
                            .order_by(
                                ApprovalFlowVersion.id.asc(),
                            )
                            .with_for_update()
                        )
                    ).all()
                )
                version_ids = [
                    int(version.id)
                    for version in versions
                    if version.id is not None
                ]
                if version_ids:
                    referenced = (
                        await session.exec(
                            select(ApprovalInstance.id)
                            .where(
                                ApprovalInstance.flow_version_id.in_(
                                    version_ids
                                )
                            )
                            .limit(1)
                            .with_for_update()
                        )
                    ).first()
                    if referenced is not None:
                        raise ApprovalConfigInUseError()

                    nodes = list(
                        (
                            await session.exec(
                                select(ApprovalNodeDefinition)
                                .where(
                                    ApprovalNodeDefinition.flow_version_id.in_(
                                        version_ids
                                    )
                                )
                                .order_by(ApprovalNodeDefinition.id.asc())
                                .with_for_update()
                            )
                        ).all()
                    )
                    for node in nodes:
                        await session.delete(node)
                    for version in versions:
                        await session.delete(version)
                await session.delete(flow)
                await session.commit()
                return True
            except Exception:
                await session.rollback()
                raise

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
    async def get_active_flow_version(
        cls,
        tenant_id: int,
        flow_definition_id: int,
        *,
        session=None,
        for_update: bool = False,
    ) -> ApprovalFlowVersion | None:
        statement = (
            select(ApprovalFlowVersion)
            .where(
                ApprovalFlowVersion.tenant_id == tenant_id,
                ApprovalFlowVersion.flow_definition_id == flow_definition_id,
                ApprovalFlowVersion.is_active == True,  # noqa: E712 — DM8 rejects `IS 1`
            )
            .order_by(ApprovalFlowVersion.version_no.desc(), ApprovalFlowVersion.id.desc())
        )
        if for_update:
            statement = statement.with_for_update()
        if session is not None:
            return (await session.exec(statement)).first()
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
    async def list_node_definitions(
        cls,
        tenant_id: int,
        flow_version_id: int,
        *,
        session=None,
    ) -> list[ApprovalNodeDefinition]:
        statement = (
            select(ApprovalNodeDefinition)
            .where(
                ApprovalNodeDefinition.tenant_id == tenant_id,
                ApprovalNodeDefinition.flow_version_id == flow_version_id,
            )
            .order_by(ApprovalNodeDefinition.node_order.asc(), ApprovalNodeDefinition.id.asc())
        )
        if session is not None:
            return list((await session.exec(statement)).all())
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

    @classmethod
    async def replace_flow_nodes_safely(
        cls,
        *,
        tenant_id: int,
        flow_definition_id: int,
        nodes_payload: list[dict],
    ) -> tuple[
        ApprovalFlowDefinition,
        ApprovalFlowVersion,
        list[ApprovalNodeDefinition],
        dict,
    ]:
        """以新版本保存节点, 旧版本及旧节点保持不可变。"""
        async with get_async_db_session() as session:
            try:
                await _lock_ordered_routes(
                    session,
                    tenant_id=tenant_id,
                    flow_definition_id=flow_definition_id,
                )
                flow = (
                    await session.exec(
                        select(ApprovalFlowDefinition)
                        .where(
                            ApprovalFlowDefinition.id
                            == flow_definition_id,
                            ApprovalFlowDefinition.tenant_id == tenant_id,
                        )
                        .with_for_update()
                    )
                ).first()
                if flow is None:
                    raise ValueError(
                        f'flow not found: {flow_definition_id}'
                    )

                current_version = (
                    await session.exec(
                        select(ApprovalFlowVersion)
                        .where(
                            ApprovalFlowVersion.tenant_id == tenant_id,
                            ApprovalFlowVersion.flow_definition_id
                            == flow_definition_id,
                            (ApprovalFlowVersion.is_active == True),  # noqa: E712
                        )
                        .order_by(
                            ApprovalFlowVersion.version_no.desc(),
                            ApprovalFlowVersion.id.desc(),
                        )
                        .with_for_update()
                    )
                ).first()
                before_snapshot = (
                    dict(current_version.definition_snapshot or {})
                    if current_version is not None
                    else {}
                )
                new_version_no = 1
                if current_version is not None:
                    current_version.is_active = False
                    session.add(current_version)
                    new_version_no = int(current_version.version_no) + 1

                new_version = ApprovalFlowVersion(
                    tenant_id=tenant_id,
                    flow_definition_id=flow_definition_id,
                    version_no=new_version_no,
                    is_active=True,
                    definition_snapshot={'nodes': nodes_payload},
                )
                session.add(new_version)
                await session.flush()

                created: list[ApprovalNodeDefinition] = []
                for index, node_data in enumerate(nodes_payload):
                    node = ApprovalNodeDefinition(
                        tenant_id=tenant_id,
                        flow_version_id=int(new_version.id),
                        node_code=node_data.get(
                            'node_code',
                            f'node_{index}',
                        ),
                        node_name=node_data.get(
                            'node_name',
                            f'Node {index + 1}',
                        ),
                        node_order=node_data.get('node_order', index),
                        node_mode=node_data.get('node_mode', 'or'),
                        approver_config=(
                            node_data.get('approver_config') or {}
                        ),
                        extra_config=node_data.get('extra_config') or {},
                    )
                    session.add(node)
                    created.append(node)
                await session.flush()
                await session.commit()
                return (
                    flow,
                    new_version,
                    created,
                    before_snapshot,
                )
            except Exception:
                await session.rollback()
                raise
