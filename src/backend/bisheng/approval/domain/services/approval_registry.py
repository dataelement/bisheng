from __future__ import annotations

from typing import Any

from bisheng.approval.domain.schemas.approval_center_schema import (
    ApprovalPresetApproverSource,
    ApprovalPresetConditionField,
    ApprovalPresetValueOption,
    ApprovalScenarioPreset,
)


def _values(items: list[tuple[str, str]]) -> list[ApprovalPresetValueOption]:
    return [ApprovalPresetValueOption(value=value, label=label) for value, label in items]


_CONDITION_FIELD_OPTIONS: dict[str, ApprovalPresetConditionField] = {
    'applicant_role': ApprovalPresetConditionField(
        field='applicant_role',
        label='申请人身份',
        type='select',
        values=_values([
            ('admin', '系统管理员'),
            ('tenant_admin', '租户管理员'),
            ('dept_admin', '部门管理员'),
        ]),
    ),
    'menu_key': ApprovalPresetConditionField(field='menu_key', label='申请菜单', type='select'),
    'space_type': ApprovalPresetConditionField(
        field='space_type',
        label='知识空间类型',
        type='select',
        values=_values([
            ('public', '公共'),
            ('department', '部门'),
            ('team', '团队'),
        ]),
    ),
    'space_level': ApprovalPresetConditionField(
        field='space_level',
        label='知识空间等级',
        type='select',
        values=_values([
            ('public', '公共'),
            ('department', '部门'),
            ('team', '团队'),
            ('personal', '个人'),
        ]),
    ),
    'space_visibility': ApprovalPresetConditionField(
        field='space_visibility',
        label='空间可见性',
        type='select',
        values=_values([
            ('released', '发布到广场'),
            ('public', '公开'),
            ('approval', '需审核'),
            ('private', '私有'),
        ]),
    ),
    'source_space_level': ApprovalPresetConditionField(
        field='source_space_level',
        label='来源知识空间等级',
        type='select',
        values=_values([
            ('public', '公共'),
            ('department', '部门'),
            ('team', '团队'),
            ('personal', '个人'),
        ]),
    ),
    'target_space_level': ApprovalPresetConditionField(
        field='target_space_level',
        label='目标知识空间等级',
        type='select',
        values=_values([
            ('public', '公共'),
            ('department', '部门'),
            ('team', '团队'),
            ('personal', '个人'),
        ]),
    ),
    'target_space_id': ApprovalPresetConditionField(
        field='target_space_id',
        label='目标知识空间',
        type='selector',
        selector_type='knowledge_space_publish_target',
    ),
}


_APPROVER_SOURCE_OPTIONS: dict[str, ApprovalPresetApproverSource] = {
    'direct_user': ApprovalPresetApproverSource(source_type='direct_user', label='指定用户'),
    'department_admin': ApprovalPresetApproverSource(source_type='department_admin', label='申请人部门管理员'),
    'tenant_admin': ApprovalPresetApproverSource(source_type='tenant_admin', label='租户管理员'),
    'channel_admin': ApprovalPresetApproverSource(source_type='channel_admin', label='频道管理员'),
    'channel_owner': ApprovalPresetApproverSource(source_type='channel_owner', label='频道 Owner'),
    'channel_manager': ApprovalPresetApproverSource(source_type='channel_manager', label='频道 Manager'),
    'space_admin': ApprovalPresetApproverSource(source_type='space_admin', label='知识空间管理员'),
    'knowledge_space_owner': ApprovalPresetApproverSource(source_type='knowledge_space_owner', label='知识空间 Owner'),
    'knowledge_space_manager': ApprovalPresetApproverSource(source_type='knowledge_space_manager', label='知识空间 Manager'),
}


def _complete_preset(preset: ApprovalScenarioPreset) -> ApprovalScenarioPreset:
    if not preset.condition_field_options:
        preset.condition_field_options = [
            _CONDITION_FIELD_OPTIONS.get(field)
            or ApprovalPresetConditionField(field=field, label=field)
            for field in preset.condition_fields
        ]
    if not preset.approver_source_options:
        preset.approver_source_options = [
            _APPROVER_SOURCE_OPTIONS.get(source_type)
            or ApprovalPresetApproverSource(source_type=source_type, label=source_type)
            for source_type in preset.approver_source_types
        ]
    return preset


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
                # applicant_role: admin / dept_admin / regular_user
                # menu_key: specific menu key from payload_snapshot
                condition_fields=['applicant_role', 'menu_key'],
                approver_source_types=['direct_user', 'department_admin'],
            )
        )
        registry.register_preset(
            ApprovalScenarioPreset(
                scenario_code='channel_subscribe_request',
                scenario_name='频道订阅审批',
                handler_key='channel_subscribe_request',
                condition_fields=['applicant_role'],
                approver_source_types=['direct_user', 'department_admin', 'channel_owner', 'channel_manager'],
            )
        )
        registry.register_preset(
            ApprovalScenarioPreset(
                scenario_code='knowledge_space_subscribe_request',
                scenario_name='知识空间加入审批',
                handler_key='knowledge_space_subscribe_request',
                condition_fields=['applicant_role'],
                approver_source_types=['direct_user', 'department_admin', 'knowledge_space_owner', 'knowledge_space_manager'],
            )
        )
        registry.register_preset(
            ApprovalScenarioPreset(
                scenario_code='knowledge_space_create_request',
                scenario_name='知识空间创建审批',
                handler_key='knowledge_space_create_request',
                condition_fields=['applicant_role', 'space_level', 'space_visibility'],
                approver_source_types=['direct_user', 'department_admin'],
            )
        )
        registry.register_preset(
            ApprovalScenarioPreset(
                scenario_code='knowledge_space_file_publish_request',
                scenario_name='知识空间文件发布审批',
                handler_key='knowledge_space_file_publish_request',
                condition_fields=['applicant_role', 'source_space_level', 'target_space_level', 'target_space_id'],
                approver_source_types=[
                    'direct_user',
                    'department_admin',
                    'knowledge_space_owner',
                    'knowledge_space_manager',
                ],
            )
        )
        return registry

    def register_preset(self, preset: ApprovalScenarioPreset) -> None:
        self._presets[preset.scenario_code] = _complete_preset(preset)

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
