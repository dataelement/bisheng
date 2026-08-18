from __future__ import annotations

from uuid import uuid4

from bisheng.approval.domain.models.approval_scenario import (
    ApprovalFlowDefinition,
    ApprovalFlowVersion,
    ApprovalRouteRule,
    ApprovalScenario,
)
from bisheng.approval.domain.repositories.approval_query_repository import ApprovalQueryRepository
from bisheng.approval.domain.repositories.approval_scenario_repository import ApprovalScenarioRepository
from bisheng.approval.domain.services.approval_registry import (
    UNIVERSAL_CONDITION_FIELDS,
    ApprovalRegistry,
)
from bisheng.common.errcode.approval import (
    ApprovalConditionOptionInvalidError,
    ApprovalFixedScenarioStructureLockedError,
)
from bisheng.database.models.audit_log import AuditLogDao


class ApprovalScenarioAdminService:
    SYSTEM_SCENARIO_CODES = frozenset({"department_file_view_request"})
    FIXED_SCENARIO_CODES = frozenset()
    # 流程管理不展示：业务自建流程，管理员不可配置。运行时仍走 registry / repository。
    ADMIN_CONFIG_HIDDEN_SCENARIO_CODES = frozenset({"qa_question_publish"})

    @classmethod
    def _is_fixed_scenario(cls, scenario) -> bool:
        return bool(scenario and getattr(scenario, "scenario_code", None) in cls.FIXED_SCENARIO_CODES)

    @classmethod
    def _is_admin_config_hidden(cls, scenario) -> bool:
        """流程管理是否隐藏该场景。可传 ORM 行或 scenario_code。"""
        code = scenario if isinstance(scenario, str) else getattr(scenario, "scenario_code", None)
        return code in cls.ADMIN_CONFIG_HIDDEN_SCENARIO_CODES

    @classmethod
    async def _assert_scenario_structure_mutable(
        cls,
        *,
        tenant_id: int,
        scenario_id: int,
    ):
        scenario = await ApprovalScenarioRepository.get_scenario(scenario_id)
        if scenario is None or scenario.tenant_id != tenant_id:
            raise ValueError(f"scenario not found: {scenario_id}")
        if cls._is_fixed_scenario(scenario) or cls._is_admin_config_hidden(scenario):
            raise ApprovalFixedScenarioStructureLockedError()
        return scenario

    @classmethod
    async def _assert_route_structure_mutable(
        cls,
        *,
        tenant_id: int,
        route_rule_id: int,
    ):
        route = await ApprovalScenarioRepository.get_route_rule(route_rule_id)
        if route is None or route.tenant_id != tenant_id:
            raise ValueError(f"route not found: {route_rule_id}")
        await cls._assert_scenario_structure_mutable(
            tenant_id=tenant_id,
            scenario_id=route.scenario_id,
        )
        return route

    @classmethod
    async def _assert_flow_structure_mutable(
        cls,
        *,
        tenant_id: int,
        flow_definition_id: int,
    ):
        flow = await ApprovalScenarioRepository.get_flow_definition(flow_definition_id)
        if flow is None or flow.tenant_id != tenant_id:
            raise ValueError(f"flow not found: {flow_definition_id}")
        await cls._assert_scenario_structure_mutable(
            tenant_id=tenant_id,
            scenario_id=flow.scenario_id,
        )
        return flow

    @classmethod
    async def list_presets(cls):
        return [
            item.model_dump()
            for item in ApprovalRegistry.with_default_presets().list_presets()
            if not cls._is_admin_config_hidden(item.scenario_code)
        ]

    @classmethod
    async def list_scenarios(cls, *, tenant_id: int):
        rows = await ApprovalScenarioRepository.list_scenarios(tenant_id)
        return [
            {
                **row.model_dump(),
                "system_managed": (getattr(row, "scenario_code", None) in cls.SYSTEM_SCENARIO_CODES),
                "structure_locked": cls._is_fixed_scenario(row),
            }
            for row in rows
            if not cls._is_admin_config_hidden(row)
        ]

    @classmethod
    async def create_scenario(
        cls,
        *,
        tenant_id: int,
        payload: dict,
        operator_user_id: int | None = None,
        operator_user_name: str | None = None,
    ):
        scenario_code = str(payload["scenario_code"])
        if scenario_code in cls.SYSTEM_SCENARIO_CODES or cls._is_admin_config_hidden(scenario_code):
            raise ApprovalFixedScenarioStructureLockedError()
        existing = await ApprovalScenarioRepository.get_scenario_by_code(tenant_id, scenario_code)
        if existing:
            return existing.model_dump()
        row = await ApprovalScenarioRepository.create_scenario(
            ApprovalScenario(
                tenant_id=tenant_id,
                scenario_code=scenario_code,
                scenario_name=payload["scenario_name"],
                enabled=bool(payload.get("enabled", False)),
                display_name=payload.get("display_name"),
            )
        )
        if operator_user_id is not None:
            await AuditLogDao.ainsert_v2(
                tenant_id=tenant_id,
                operator_id=operator_user_id,
                operator_tenant_id=tenant_id,
                action="approval.scenario.create",
                target_type="approval_scenario",
                target_id=str(row.id),
                metadata={"scenario_code": row.scenario_code, "enabled": row.enabled},
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
        operator_user_id: int | None = None,
        operator_user_name: str | None = None,
        ip_address: str | None = None,
    ):
        row = await ApprovalScenarioRepository.get_scenario(scenario_id)
        if row is None or row.tenant_id != tenant_id:
            raise ValueError(f"scenario not found: {scenario_id}")
        if cls._is_admin_config_hidden(row):
            raise ApprovalFixedScenarioStructureLockedError()
        if cls._is_fixed_scenario(row):
            extra_fields = set(payload) - {"enabled", "toggle_reason"}
            if extra_fields:
                raise ApprovalFixedScenarioStructureLockedError()
        before_enabled = row.enabled
        if payload.get("scenario_name"):
            row.scenario_name = payload["scenario_name"]
        if "enabled" in payload:
            row.enabled = bool(payload["enabled"])
        if "display_name" in payload:
            row.display_name = payload["display_name"]
        updated = await ApprovalScenarioRepository.update_scenario(row)
        if operator_user_id is not None and "enabled" in payload and bool(payload["enabled"]) != bool(before_enabled):
            await AuditLogDao.ainsert_v2(
                tenant_id=tenant_id,
                operator_id=operator_user_id,
                operator_tenant_id=tenant_id,
                action="approval.scenario.toggle",
                target_type="approval_scenario",
                target_id=str(updated.id),
                reason=payload.get("toggle_reason"),
                metadata={
                    "scenario_code": updated.scenario_code,
                    "before_enabled": bool(before_enabled),
                    "after_enabled": bool(updated.enabled),
                },
                operator_name=operator_user_name,
                object_name=updated.scenario_name,
                ip_address=ip_address,
            )
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
        scenario = await cls._assert_scenario_structure_mutable(
            tenant_id=tenant_id,
            scenario_id=scenario_id,
        )
        await cls._validate_route_payload(
            tenant_id=tenant_id,
            scenario=scenario,
            payload=payload,
        )
        row = await ApprovalScenarioRepository.create_route_rule_safely(
            ApprovalRouteRule(
                tenant_id=tenant_id,
                scenario_id=scenario_id,
                route_name=payload["route_name"],
                route_type=payload["route_type"],
                sort_order=int(payload.get("sort_order", 0)),
                flow_definition_id=payload.get("flow_definition_id"),
                match_config=payload.get("match_config") or {},
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
        row = await cls._assert_route_structure_mutable(
            tenant_id=tenant_id,
            route_rule_id=route_rule_id,
        )
        scenario = await ApprovalScenarioRepository.get_scenario(row.scenario_id)
        merged_payload = {
            "route_name": row.route_name,
            "route_type": row.route_type,
            "sort_order": row.sort_order,
            "flow_definition_id": row.flow_definition_id,
            "match_config": row.match_config or {},
            "enabled": row.enabled,
            **payload,
        }
        await cls._validate_route_payload(
            tenant_id=tenant_id,
            scenario=scenario,
            payload=merged_payload,
        )
        updated = await ApprovalScenarioRepository.update_route_rule_safely(
            tenant_id=tenant_id,
            route_rule_id=route_rule_id,
            payload=payload,
        )
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
        await cls._assert_scenario_structure_mutable(
            tenant_id=tenant_id,
            scenario_id=scenario_id,
        )
        flow = await ApprovalScenarioRepository.create_flow_definition(
            ApprovalFlowDefinition(
                tenant_id=tenant_id,
                scenario_id=scenario_id,
                flow_code=payload.get("flow_code") or f"flow_{uuid4().hex[:8]}",
                flow_name=payload["flow_name"],
                is_active=bool(payload.get("is_active", True)),
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
        await cls._assert_flow_structure_mutable(
            tenant_id=tenant_id,
            flow_definition_id=flow_definition_id,
        )
        # flow_code is auto-generated and not user-editable
        updated = await ApprovalScenarioRepository.update_flow_definition_safely(
            tenant_id=tenant_id,
            flow_definition_id=flow_definition_id,
            payload=payload,
        )
        return updated.model_dump()

    @classmethod
    async def list_nodes(cls, *, tenant_id: int, flow_definition_id: int):
        flow = await ApprovalScenarioRepository.get_flow_definition(flow_definition_id)
        if flow is None or flow.tenant_id != tenant_id:
            raise ValueError(f"flow not found: {flow_definition_id}")
        version = await ApprovalScenarioRepository.get_active_flow_version(tenant_id, flow_definition_id)
        if version is None:
            return []
        rows = await ApprovalScenarioRepository.list_node_definitions(tenant_id, version.id)
        return [row.model_dump() for row in rows]

    @classmethod
    async def delete_scenario(cls, *, tenant_id: int, scenario_id: int) -> None:
        scenario = await cls._assert_scenario_structure_mutable(
            tenant_id=tenant_id,
            scenario_id=scenario_id,
        )
        if scenario.scenario_code in cls.SYSTEM_SCENARIO_CODES:
            raise ApprovalFixedScenarioStructureLockedError()
        await ApprovalScenarioRepository.delete_scenario(scenario_id)

    @classmethod
    async def delete_route(cls, *, tenant_id: int, route_rule_id: int) -> None:
        await cls._assert_route_structure_mutable(
            tenant_id=tenant_id,
            route_rule_id=route_rule_id,
        )
        await ApprovalScenarioRepository.delete_route_rule_safely(
            tenant_id=tenant_id,
            route_rule_id=route_rule_id,
        )

    @classmethod
    async def reorder_routes(cls, *, tenant_id: int, scenario_id: int, ordered_route_ids: list[int]) -> None:
        await cls._assert_scenario_structure_mutable(
            tenant_id=tenant_id,
            scenario_id=scenario_id,
        )
        await ApprovalScenarioRepository.bulk_update_route_sort_order_safely(
            tenant_id=tenant_id,
            scenario_id=scenario_id,
            ordered_route_ids=ordered_route_ids,
        )

    @classmethod
    async def delete_flow(cls, *, tenant_id: int, flow_definition_id: int) -> None:
        await cls._assert_flow_structure_mutable(
            tenant_id=tenant_id,
            flow_definition_id=flow_definition_id,
        )
        await ApprovalScenarioRepository.delete_flow_definition_safely(
            tenant_id=tenant_id,
            flow_definition_id=flow_definition_id,
        )

    @classmethod
    async def list_condition_options(
        cls,
        *,
        tenant_id: int,
        scenario_id: int,
        field: str,
        keyword: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        scenario = await ApprovalScenarioRepository.get_scenario(scenario_id)
        if scenario is None or scenario.tenant_id != tenant_id:
            raise ApprovalConditionOptionInvalidError()
        preset = ApprovalRegistry.with_default_presets().get_preset(scenario.scenario_code)
        descriptors = {
            descriptor.field: descriptor for descriptor in (preset.condition_field_options if preset else [])
        }
        descriptor = descriptors.get(field)
        if descriptor is None or descriptor.type != "selector" or field != "file_knowledge_space_id":
            raise ApprovalConditionOptionInvalidError()

        from bisheng.knowledge.domain.services.knowledge_space_service import (
            KnowledgeSpaceService,
        )

        return await KnowledgeSpaceService.list_valid_department_space_options(
            keyword=keyword,
            page=page,
            page_size=page_size,
        )

    @classmethod
    async def _validate_route_payload(
        cls,
        *,
        tenant_id: int,
        scenario,
        payload: dict,
    ) -> None:
        if scenario is None or scenario.tenant_id != tenant_id:
            raise ApprovalConditionOptionInvalidError()

        route_type = str(payload.get("route_type") or "")
        flow_definition_id = payload.get("flow_definition_id")
        if route_type == "pass":
            if flow_definition_id is not None:
                raise ApprovalConditionOptionInvalidError()
        elif route_type in {"flow", "approval"}:
            if not flow_definition_id:
                raise ApprovalConditionOptionInvalidError()
            flow = await ApprovalScenarioRepository.get_flow_definition(int(flow_definition_id))
            if flow is None or flow.tenant_id != tenant_id or flow.scenario_id != scenario.id or not flow.is_active:
                raise ApprovalConditionOptionInvalidError()
        else:
            raise ApprovalConditionOptionInvalidError()

        preset = ApprovalRegistry.with_default_presets().get_preset(scenario.scenario_code)
        allowed_fields = set(preset.condition_fields if preset else []) | set(UNIVERSAL_CONDITION_FIELDS)
        match_config = payload.get("match_config") or {}
        raw_conditions = match_config.get("conditions")
        if raw_conditions is None:
            raw_conditions = [match_config] if match_config.get("field") else []
        if not isinstance(raw_conditions, list):
            raise ApprovalConditionOptionInvalidError()
        if "operator" in match_config:
            operator = str(match_config.get("operator") or "").lower()
            if operator != "and":
                raise ApprovalConditionOptionInvalidError()

        from bisheng.knowledge.domain.services.knowledge_space_service import (
            KnowledgeSpaceService,
        )

        for condition in raw_conditions:
            if not isinstance(condition, dict):
                raise ApprovalConditionOptionInvalidError()
            field = str(condition.get("field") or "")
            value = str(condition.get("value") or "")
            if not field or field not in allowed_fields or not value:
                raise ApprovalConditionOptionInvalidError()
            if field != "file_knowledge_space_id":
                continue
            try:
                space_id = int(value)
            except (TypeError, ValueError):
                raise ApprovalConditionOptionInvalidError() from None
            if not await KnowledgeSpaceService.is_valid_department_space_id(space_id):
                raise ApprovalConditionOptionInvalidError()

    @classmethod
    async def get_flow_version(cls, *, tenant_id: int, flow_definition_id: int, flow_version_id: int):
        flow = await ApprovalScenarioRepository.get_flow_definition(flow_definition_id)
        if flow is None or flow.tenant_id != tenant_id:
            raise ValueError(f"flow not found: {flow_definition_id}")
        version = await ApprovalScenarioRepository.get_flow_version(flow_version_id)
        if version is None or version.flow_definition_id != flow_definition_id:
            raise ValueError(f"version not found: {flow_version_id}")
        nodes = await ApprovalScenarioRepository.list_node_definitions(tenant_id, version.id)
        return {**version.model_dump(), "nodes": [n.model_dump() for n in nodes]}

    @classmethod
    async def set_flow_nodes(
        cls,
        *,
        tenant_id: int,
        flow_definition_id: int,
        nodes_payload: list[dict],
        operator_user_id: int | None = None,
        operator_user_name: str | None = None,
        ip_address: str | None = None,
    ):
        flow = await cls._assert_flow_structure_mutable(
            tenant_id=tenant_id,
            flow_definition_id=flow_definition_id,
        )
        (
            flow,
            new_version,
            created_rows,
            before_snapshot,
        ) = await ApprovalScenarioRepository.replace_flow_nodes_safely(
            tenant_id=tenant_id,
            flow_definition_id=flow_definition_id,
            nodes_payload=nodes_payload,
        )
        created = [row.model_dump() for row in created_rows]
        new_version_no = int(new_version.version_no)
        if operator_user_id is not None:
            scenario_code: str | None = None
            try:
                scenario = await ApprovalScenarioRepository.get_scenario(flow.scenario_id)
                scenario_code = scenario.scenario_code if scenario else None
            except Exception:
                scenario_code = None
            await AuditLogDao.ainsert_v2(
                tenant_id=tenant_id,
                operator_id=operator_user_id,
                operator_tenant_id=tenant_id,
                action="approval.flow.update",
                target_type="approval_flow",
                target_id=str(flow_definition_id),
                metadata={
                    "flow_definition_id": flow_definition_id,
                    "scenario_code": scenario_code,
                    "before_snapshot": before_snapshot,
                    "after_snapshot": {"nodes": nodes_payload},
                },
                operator_name=operator_user_name,
                object_name=flow.flow_name,
                ip_address=ip_address,
            )
        return {"flow_version_id": new_version.id, "version_no": new_version_no, "nodes": created}

    @classmethod
    async def list_open_exceptions(cls, *, tenant_id: int):
        from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository

        rows = await ApprovalQueryRepository.list_open_exceptions(tenant_id)
        result = []
        for row in rows:
            item = row.model_dump()
            instance = await ApprovalInstanceRepository.get_instance(row.instance_id)
            if instance:
                item["business_name"] = instance.business_name
                item["scenario_code"] = instance.scenario_code
                item["scenario_name"] = instance.scenario_name
                item["applicant_user_name"] = instance.applicant_user_name
            result.append(item)
        return result
