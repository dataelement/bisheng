from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_scenario import (
    ApprovalFlowDefinition,
    ApprovalFlowVersion,
    ApprovalNodeDefinition,
    ApprovalRouteRule,
    ApprovalScenario,
)
from bisheng.common.errcode.approval import (
    ApprovalFixedScenarioInvalidError,
    ApprovalScenarioDisabledError,
)


@dataclass(frozen=True)
class FixedScenarioContract:
    scenario: ApprovalScenario
    route: ApprovalRouteRule
    flow: ApprovalFlowDefinition
    flow_version: ApprovalFlowVersion
    node: ApprovalNodeDefinition


class FixedScenarioProvisioner:
    SCENARIO_CODE = "department_file_view_request"
    FLOW_CODE = "department_file_view_fixed_flow"
    ROUTE_NAME = "部门文件查看固定审批路由"
    NODE_CODE = "department_file_owner_approvers"
    APPROVER_CONFIG = {
        "sources": [{"type": "department_file_approvers"}],
    }

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_contract(
        self,
        *,
        tenant_id: int,
        require_enabled: bool = True,
    ) -> FixedScenarioContract:
        scenario = (
            (
                await self.session.execute(
                    select(ApprovalScenario).where(
                        ApprovalScenario.tenant_id == tenant_id,
                        ApprovalScenario.scenario_code == self.SCENARIO_CODE,
                    )
                )
            )
            .scalars()
            .first()
        )
        if scenario is None:
            raise ApprovalFixedScenarioInvalidError()
        if require_enabled and not scenario.enabled:
            raise ApprovalScenarioDisabledError()

        routes = list(
            (
                await self.session.execute(
                    select(ApprovalRouteRule)
                    .where(
                        ApprovalRouteRule.tenant_id == tenant_id,
                        ApprovalRouteRule.scenario_id == scenario.id,
                    )
                    .order_by(
                        ApprovalRouteRule.sort_order.asc(),
                        ApprovalRouteRule.id.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        flows = list(
            (
                await self.session.execute(
                    select(ApprovalFlowDefinition).where(
                        ApprovalFlowDefinition.tenant_id == tenant_id,
                        ApprovalFlowDefinition.scenario_id == scenario.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        if len(routes) != 1 or len(flows) != 1:
            raise ApprovalFixedScenarioInvalidError()
        route = routes[0]
        flow = flows[0]
        if not (
            route.enabled
            and route.route_name == self.ROUTE_NAME
            and route.route_type == "approval"
            and int(route.flow_definition_id or 0) == int(flow.id)
            and (route.match_config or {}) == {}
            and flow.flow_code == self.FLOW_CODE
            and flow.is_active
        ):
            raise ApprovalFixedScenarioInvalidError()

        versions = list(
            (
                await self.session.execute(
                    select(ApprovalFlowVersion)
                    .where(
                        ApprovalFlowVersion.tenant_id == tenant_id,
                        ApprovalFlowVersion.flow_definition_id == flow.id,
                        ApprovalFlowVersion.is_active == True,  # noqa: E712
                    )
                    .order_by(
                        ApprovalFlowVersion.version_no.desc(),
                        ApprovalFlowVersion.id.desc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        if len(versions) != 1:
            raise ApprovalFixedScenarioInvalidError()
        flow_version = versions[0]

        nodes = list(
            (
                await self.session.execute(
                    select(ApprovalNodeDefinition)
                    .where(
                        ApprovalNodeDefinition.tenant_id == tenant_id,
                        ApprovalNodeDefinition.flow_version_id == flow_version.id,
                    )
                    .order_by(
                        ApprovalNodeDefinition.node_order.asc(),
                        ApprovalNodeDefinition.id.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        if len(nodes) != 1:
            raise ApprovalFixedScenarioInvalidError()
        node = nodes[0]
        if not (
            node.node_code == self.NODE_CODE
            and node.node_order == 0
            and node.node_mode == "or"
            and (node.approver_config or {}) == self.APPROVER_CONFIG
        ):
            raise ApprovalFixedScenarioInvalidError()
        return FixedScenarioContract(
            scenario=scenario,
            route=route,
            flow=flow,
            flow_version=flow_version,
            node=node,
        )
