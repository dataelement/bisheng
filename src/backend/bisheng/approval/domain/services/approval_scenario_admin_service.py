from __future__ import annotations

from uuid import uuid4

from bisheng.approval.domain.models.approval_scenario import (
    ApprovalFlowDefinition,
    ApprovalFlowVersion,
    ApprovalNodeDefinition,
    ApprovalRouteRule,
    ApprovalScenario,
)
from bisheng.approval.domain.repositories.approval_query_repository import ApprovalQueryRepository
from bisheng.approval.domain.repositories.approval_scenario_repository import ApprovalScenarioRepository
from bisheng.approval.domain.services.approval_registry import ApprovalRegistry
from bisheng.database.models.audit_log import AuditLogDao


class ApprovalScenarioAdminService:
    @classmethod
    async def list_presets(cls):
        return [item.model_dump() for item in ApprovalRegistry.with_default_presets().list_presets()]

    @classmethod
    async def list_scenarios(cls, *, tenant_id: int):
        rows = await ApprovalScenarioRepository.list_scenarios(tenant_id)
        return [row.model_dump() for row in rows]

    @classmethod
    async def create_scenario(
        cls,
        *,
        tenant_id: int,
        payload: dict,
        operator_user_id: int | None = None,
        operator_user_name: str | None = None,
    ):
        scenario_code = str(payload['scenario_code'])
        existing = await ApprovalScenarioRepository.get_scenario_by_code(tenant_id, scenario_code)
        if existing:
            return existing.model_dump()
        row = await ApprovalScenarioRepository.create_scenario(
            ApprovalScenario(
                tenant_id=tenant_id,
                scenario_code=scenario_code,
                scenario_name=payload['scenario_name'],
                enabled=bool(payload.get('enabled', False)),
                display_name=payload.get('display_name'),
            )
        )
        if operator_user_id is not None:
            await AuditLogDao.ainsert_v2(
                tenant_id=tenant_id,
                operator_id=operator_user_id,
                operator_tenant_id=tenant_id,
                action='approval.scenario.create',
                target_type='approval_scenario',
                target_id=str(row.id),
                metadata={'scenario_code': row.scenario_code, 'enabled': row.enabled},
                operator_name=operator_user_name,
            )
        return row.model_dump()

    @classmethod
    async def update_scenario(
        cls,
        *,
        tenant_id: int,
        scenario_id: int,
        payload: dict,
    ):
        row = await ApprovalScenarioRepository.get_scenario(scenario_id)
        if row is None or row.tenant_id != tenant_id:
            raise ValueError(f'scenario not found: {scenario_id}')
        if 'scenario_name' in payload and payload['scenario_name']:
            row.scenario_name = payload['scenario_name']
        if 'enabled' in payload:
            row.enabled = bool(payload['enabled'])
        if 'display_name' in payload:
            row.display_name = payload['display_name']
        updated = await ApprovalScenarioRepository.update_scenario(row)
        return updated.model_dump()

    @classmethod
    async def list_routes(cls, *, tenant_id: int, scenario_id: int):
        rows = await ApprovalScenarioRepository.list_route_rules(tenant_id, scenario_id)
        return [row.model_dump() for row in rows]

    @classmethod
    async def create_route(
        cls,
        *,
        tenant_id: int,
        scenario_id: int,
        payload: dict,
    ):
        row = await ApprovalScenarioRepository.create_route_rule(
            ApprovalRouteRule(
                tenant_id=tenant_id,
                scenario_id=scenario_id,
                route_name=payload['route_name'],
                route_type=payload['route_type'],
                sort_order=int(payload.get('sort_order', 0)),
                flow_definition_id=payload.get('flow_definition_id'),
                match_config=payload.get('match_config') or {},
            )
        )
        return row.model_dump()

    @classmethod
    async def update_route(
        cls,
        *,
        tenant_id: int,
        route_rule_id: int,
        payload: dict,
    ):
        row = await ApprovalScenarioRepository.get_route_rule(route_rule_id)
        if row is None or row.tenant_id != tenant_id:
            raise ValueError(f'route not found: {route_rule_id}')
        if 'route_name' in payload and payload['route_name']:
            row.route_name = payload['route_name']
        if 'route_type' in payload and payload['route_type']:
            row.route_type = payload['route_type']
        if 'sort_order' in payload:
            row.sort_order = int(payload['sort_order'])
        if 'flow_definition_id' in payload:
            row.flow_definition_id = payload['flow_definition_id']
        if 'match_config' in payload:
            row.match_config = payload['match_config'] or {}
        if 'enabled' in payload:
            row.enabled = bool(payload['enabled'])
        updated = await ApprovalScenarioRepository.update_route_rule(row)
        return updated.model_dump()

    @classmethod
    async def list_flows(cls, *, tenant_id: int, scenario_id: int):
        rows = await ApprovalScenarioRepository.list_flow_definitions(tenant_id, scenario_id)
        return [row.model_dump() for row in rows]

    @classmethod
    async def create_flow(
        cls,
        *,
        tenant_id: int,
        scenario_id: int,
        payload: dict,
    ):
        flow = await ApprovalScenarioRepository.create_flow_definition(
            ApprovalFlowDefinition(
                tenant_id=tenant_id,
                scenario_id=scenario_id,
                flow_code=payload.get('flow_code') or f'flow_{uuid4().hex[:8]}',
                flow_name=payload['flow_name'],
                is_active=bool(payload.get('is_active', True)),
            )
        )
        await ApprovalScenarioRepository.create_flow_version(
            ApprovalFlowVersion(
                tenant_id=tenant_id,
                flow_definition_id=flow.id,
                version_no=1,
                is_active=True,
                definition_snapshot={},
            )
        )
        return flow.model_dump()

    @classmethod
    async def update_flow(
        cls,
        *,
        tenant_id: int,
        flow_definition_id: int,
        payload: dict,
    ):
        row = await ApprovalScenarioRepository.get_flow_definition(flow_definition_id)
        if row is None or row.tenant_id != tenant_id:
            raise ValueError(f'flow not found: {flow_definition_id}')
        if 'flow_name' in payload and payload['flow_name']:
            row.flow_name = payload['flow_name']
        # flow_code is auto-generated and not user-editable
        if 'is_active' in payload:
            row.is_active = bool(payload['is_active'])
        updated = await ApprovalScenarioRepository.update_flow_definition(row)
        return updated.model_dump()

    @classmethod
    async def list_nodes(cls, *, tenant_id: int, flow_definition_id: int):
        flow = await ApprovalScenarioRepository.get_flow_definition(flow_definition_id)
        if flow is None or flow.tenant_id != tenant_id:
            raise ValueError(f'flow not found: {flow_definition_id}')
        version = await ApprovalScenarioRepository.get_active_flow_version(tenant_id, flow_definition_id)
        if version is None:
            return []
        rows = await ApprovalScenarioRepository.list_node_definitions(tenant_id, version.id)
        return [row.model_dump() for row in rows]

    @classmethod
    async def delete_scenario(cls, *, tenant_id: int, scenario_id: int) -> None:
        row = await ApprovalScenarioRepository.get_scenario(scenario_id)
        if row is None or row.tenant_id != tenant_id:
            raise ValueError(f'scenario not found: {scenario_id}')
        await ApprovalScenarioRepository.delete_scenario(scenario_id)

    @classmethod
    async def delete_route(cls, *, tenant_id: int, route_rule_id: int) -> None:
        row = await ApprovalScenarioRepository.get_route_rule(route_rule_id)
        if row is None or row.tenant_id != tenant_id:
            raise ValueError(f'route not found: {route_rule_id}')
        await ApprovalScenarioRepository.delete_route_rule(route_rule_id)

    @classmethod
    async def reorder_routes(cls, *, tenant_id: int, scenario_id: int, ordered_route_ids: list[int]) -> None:
        existing = await ApprovalScenarioRepository.list_route_rules(tenant_id, scenario_id)
        existing_ids = {r.id for r in existing}
        for rid in ordered_route_ids:
            if rid not in existing_ids:
                raise ValueError(f'route {rid} does not belong to scenario {scenario_id}')
        await ApprovalScenarioRepository.bulk_update_route_sort_order(ordered_route_ids)

    @classmethod
    async def delete_flow(cls, *, tenant_id: int, flow_definition_id: int) -> None:
        row = await ApprovalScenarioRepository.get_flow_definition(flow_definition_id)
        if row is None or row.tenant_id != tenant_id:
            raise ValueError(f'flow not found: {flow_definition_id}')
        await ApprovalScenarioRepository.delete_flow_definition(flow_definition_id)

    @classmethod
    async def get_flow_version(cls, *, tenant_id: int, flow_definition_id: int, flow_version_id: int):
        flow = await ApprovalScenarioRepository.get_flow_definition(flow_definition_id)
        if flow is None or flow.tenant_id != tenant_id:
            raise ValueError(f'flow not found: {flow_definition_id}')
        version = await ApprovalScenarioRepository.get_flow_version(flow_version_id)
        if version is None or version.flow_definition_id != flow_definition_id:
            raise ValueError(f'version not found: {flow_version_id}')
        nodes = await ApprovalScenarioRepository.list_node_definitions(tenant_id, version.id)
        return {**version.model_dump(), 'nodes': [n.model_dump() for n in nodes]}

    @classmethod
    async def set_flow_nodes(cls, *, tenant_id: int, flow_definition_id: int, nodes_payload: list[dict]):
        flow = await ApprovalScenarioRepository.get_flow_definition(flow_definition_id)
        if flow is None or flow.tenant_id != tenant_id:
            raise ValueError(f'flow not found: {flow_definition_id}')
        current_version = await ApprovalScenarioRepository.get_active_flow_version(tenant_id, flow_definition_id)
        if current_version:
            current_version.is_active = False
            await ApprovalScenarioRepository.update_flow_version(current_version)
            new_version_no = current_version.version_no + 1
        else:
            new_version_no = 1
        new_version = await ApprovalScenarioRepository.create_flow_version(
            ApprovalFlowVersion(
                tenant_id=tenant_id,
                flow_definition_id=flow_definition_id,
                version_no=new_version_no,
                is_active=True,
                definition_snapshot={'nodes': nodes_payload},
            )
        )
        created = []
        for idx, node_data in enumerate(nodes_payload):
            row = await ApprovalScenarioRepository.create_node_definition(
                ApprovalNodeDefinition(
                    tenant_id=tenant_id,
                    flow_version_id=new_version.id,
                    node_code=node_data.get('node_code', f'node_{idx}'),
                    node_name=node_data.get('node_name', f'Node {idx + 1}'),
                    node_order=node_data.get('node_order', idx),
                    node_mode=node_data.get('node_mode', 'or'),
                    approver_config=node_data.get('approver_config') or {},
                    extra_config=node_data.get('extra_config') or {},
                )
            )
            created.append(row.model_dump())
        return {'flow_version_id': new_version.id, 'version_no': new_version_no, 'nodes': created}

    @classmethod
    async def list_open_exceptions(cls, *, tenant_id: int):
        from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
        rows = await ApprovalQueryRepository.list_open_exceptions(tenant_id)
        result = []
        for row in rows:
            item = row.model_dump()
            instance = await ApprovalInstanceRepository.get_instance(row.instance_id)
            if instance:
                item['business_name'] = instance.business_name
                item['scenario_code'] = instance.scenario_code
                item['scenario_name'] = instance.scenario_name
                item['applicant_user_name'] = instance.applicant_user_name
            result.append(item)
        return result
