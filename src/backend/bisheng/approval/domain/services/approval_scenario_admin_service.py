from __future__ import annotations

from bisheng.approval.domain.models.approval_scenario import ApprovalRouteRule, ApprovalScenario
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
    async def list_open_exceptions(cls, *, tenant_id: int):
        rows = await ApprovalQueryRepository.list_open_exceptions(tenant_id)
        return [row.model_dump() for row in rows]
