from __future__ import annotations

from typing import Any

from bisheng.approval.domain.schemas.approval_center_schema import ApprovalScenarioPreset


class ApprovalRegistry:
    def __init__(self) -> None:
        self._presets: dict[str, ApprovalScenarioPreset] = {}
        self._handlers: dict[str, Any] = {}

    @classmethod
    def with_default_presets(cls) -> 'ApprovalRegistry':
        registry = cls()
        registry.register_preset(
            ApprovalScenarioPreset(
                scenario_code='menu_access_request',
                scenario_name='菜单权限申请',
                handler_key='menu_access_request',
                condition_fields=['menu_key', 'applicant_department_id'],
                approver_source_types=['direct_user', 'tenant_admin', 'department_admin'],
            )
        )
        registry.register_preset(
            ApprovalScenarioPreset(
                scenario_code='channel_subscribe_request',
                scenario_name='频道订阅审批',
                handler_key='channel_subscribe_request',
                condition_fields=['channel_id', 'channel_type'],
                approver_source_types=['direct_user', 'channel_admin', 'department_admin'],
            )
        )
        registry.register_preset(
            ApprovalScenarioPreset(
                scenario_code='knowledge_space_subscribe_request',
                scenario_name='知识空间加入审批',
                handler_key='knowledge_space_subscribe_request',
                condition_fields=['space_id', 'space_type', 'applicant_department_id'],
                approver_source_types=['direct_user', 'space_admin', 'department_admin'],
            )
        )
        return registry

    def register_preset(self, preset: ApprovalScenarioPreset) -> None:
        self._presets[preset.scenario_code] = preset

    def list_presets(self) -> list[ApprovalScenarioPreset]:
        return list(self._presets.values())

    def get_preset(self, scenario_code: str) -> ApprovalScenarioPreset | None:
        return self._presets.get(scenario_code)

    def register_handler(self, scenario_code: str, handler: Any) -> None:
        self._handlers[scenario_code] = handler

    async def get_handler(self, scenario_code: str) -> Any:
        handler = self._handlers.get(scenario_code)
        if handler is None:
            raise KeyError(f'handler not registered for scenario_code={scenario_code}')
        return handler
