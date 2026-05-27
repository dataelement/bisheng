"""Regression tests for PRD §9.1 audit-log emission.

These cover the audit writes that previous releases either skipped or
mislabelled. Each test patches only the DAO entry points so the production
service code runs end-to-end inside the test.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.approval.domain.services.approval_outbox_service import ApprovalOutboxService
from bisheng.approval.domain.services.approval_scenario_admin_service import (
    ApprovalScenarioAdminService,
)


class _FakeScenario:
    def __init__(self, **kw):
        self.id = kw.get('id', 42)
        self.tenant_id = kw.get('tenant_id', 1)
        self.scenario_code = kw.get('scenario_code', 'menu_access_request')
        self.scenario_name = kw.get('scenario_name', '菜单权限申请')
        self.enabled = kw.get('enabled', True)
        self.display_name = kw.get('display_name')

    def model_dump(self):
        return {
            'id': self.id,
            'tenant_id': self.tenant_id,
            'scenario_code': self.scenario_code,
            'scenario_name': self.scenario_name,
            'enabled': self.enabled,
            'display_name': self.display_name,
        }


async def test_update_scenario_writes_toggle_audit_when_enabled_flips():
    scenario = _FakeScenario(enabled=True)
    captured: list[dict] = []

    async def fake_ainsert_v2(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(id=999)

    with patch(
        'bisheng.approval.domain.services.approval_scenario_admin_service.'
        'ApprovalScenarioRepository.get_scenario',
        new=AsyncMock(return_value=scenario),
    ), patch(
        'bisheng.approval.domain.services.approval_scenario_admin_service.'
        'ApprovalScenarioRepository.update_scenario',
        new=AsyncMock(return_value=scenario),
    ), patch(
        'bisheng.approval.domain.services.approval_scenario_admin_service.'
        'AuditLogDao.ainsert_v2',
        new=AsyncMock(side_effect=fake_ainsert_v2),
    ):
        await ApprovalScenarioAdminService.update_scenario(
            tenant_id=1,
            scenario_id=42,
            payload={'enabled': False},
            operator_user_id=7,
            operator_user_name='admin',
            ip_address='10.0.0.1',
        )

    assert len(captured) == 1, 'audit log not written on enabled flip'
    row = captured[0]
    assert row['action'] == 'approval.scenario.toggle'
    assert row['target_type'] == 'approval_scenario'
    assert row['target_id'] == '42'
    assert row['operator_id'] == 7
    assert row['ip_address'] == '10.0.0.1'
    assert row['metadata']['scenario_code'] == 'menu_access_request'
    assert row['metadata']['before_enabled'] is True
    assert row['metadata']['after_enabled'] is False


async def test_update_scenario_skips_toggle_audit_when_enabled_unchanged():
    scenario = _FakeScenario(enabled=True)
    captured: list[dict] = []

    with patch(
        'bisheng.approval.domain.services.approval_scenario_admin_service.'
        'ApprovalScenarioRepository.get_scenario',
        new=AsyncMock(return_value=scenario),
    ), patch(
        'bisheng.approval.domain.services.approval_scenario_admin_service.'
        'ApprovalScenarioRepository.update_scenario',
        new=AsyncMock(return_value=scenario),
    ), patch(
        'bisheng.approval.domain.services.approval_scenario_admin_service.'
        'AuditLogDao.ainsert_v2',
        new=AsyncMock(side_effect=lambda **kw: captured.append(kw)),
    ):
        # Same enabled value: rename only, no toggle.
        await ApprovalScenarioAdminService.update_scenario(
            tenant_id=1,
            scenario_id=42,
            payload={'enabled': True, 'scenario_name': 'renamed'},
            operator_user_id=7,
            operator_user_name='admin',
        )

    assert captured == [], 'toggle audit must not fire when enabled unchanged'


async def test_outbox_success_emits_handler_success_audit():
    captured: list[dict] = []

    instance = SimpleNamespace(
        id=11,
        tenant_id=1,
        scenario_code='menu_access_request',
        handler_key='menu_access_request',
        business_name='菜单权限申请',
        status='approved',
    )
    outbox = SimpleNamespace(
        id=77,
        instance_id=11,
        status='pending',
        retry_count=0,
        error_summary=None,
        payload_snapshot={'menu_key': 'flow'},
    )

    repo = SimpleNamespace(
        get_outbox=AsyncMock(return_value=outbox),
        update_outbox=AsyncMock(),
        get_instance=AsyncMock(return_value=instance),
        update_instance=AsyncMock(),
        create_exception=AsyncMock(),
    )

    with patch(
        'bisheng.approval.domain.services.approval_outbox_service.AuditLogDao.ainsert_v2',
        new=AsyncMock(side_effect=lambda **kw: captured.append(kw)),
    ):
        service = ApprovalOutboxService(instance_repository=repo)
        result = await service.execute_outbox(outbox_id=77, executor=lambda _outbox: (True, None))

    assert result is True
    assert len(captured) == 1
    row = captured[0]
    assert row['action'] == 'approval.handler.success'
    assert row['operator_id'] == 0  # system
    assert row['metadata']['outbox_id'] == 77
    assert row['metadata']['handler'] == 'menu_access_request'
    assert row['metadata']['business_result'] == 'success'


async def test_outbox_failure_emits_handler_failed_audit_with_error_summary():
    captured: list[dict] = []
    instance = SimpleNamespace(
        id=11,
        tenant_id=1,
        scenario_code='menu_access_request',
        handler_key='menu_access_request',
        business_name='菜单权限申请',
        status='approved',
    )
    outbox = SimpleNamespace(
        id=77,
        instance_id=11,
        status='pending',
        retry_count=0,
        error_summary=None,
        payload_snapshot={'menu_key': 'flow'},
    )
    repo = SimpleNamespace(
        get_outbox=AsyncMock(return_value=outbox),
        update_outbox=AsyncMock(),
        get_instance=AsyncMock(return_value=instance),
        update_instance=AsyncMock(),
        create_exception=AsyncMock(),
    )

    with patch(
        'bisheng.approval.domain.services.approval_outbox_service.AuditLogDao.ainsert_v2',
        new=AsyncMock(side_effect=lambda **kw: captured.append(kw)),
    ):
        service = ApprovalOutboxService(instance_repository=repo)
        result = await service.execute_outbox(
            outbox_id=77,
            executor=lambda _outbox: (False, 'boom: downstream 500'),
        )

    assert result is False
    assert len(captured) == 1
    row = captured[0]
    assert row['action'] == 'approval.handler.failed'
    assert row['reason'] == 'boom: downstream 500'
    assert row['metadata']['error_stack_summary'] == 'boom: downstream 500'
    assert row['metadata']['payload_snapshot'] == {'menu_key': 'flow'}
