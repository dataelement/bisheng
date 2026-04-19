"""Tests for F012 UserTenantSyncService.

All dependencies are mocked so the tests exercise the orchestration logic
in isolation:
  - ``TenantResolver.resolve_user_leaf_tenant``
  - ``UserTenantDao.aget_active_user_tenant`` / ``aactivate_user_tenant``
  - ``UserDao.aincrement_token_version``
  - ``PermissionService.batch_write_tuples``
  - ``AuditLogDao.ainsert_v2``
  - Redis client (cache invalidation)
  - ``_count_owned_resources`` (replaced with an AsyncMock)

Covers spec §5.2 (sync flow), AC-03 / AC-04 / AC-05 / AC-06 / AC-07 of F012.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.common.errcode.tenant_resolver import TenantRelocateBlockedError
from bisheng.tenant.domain.constants import (
    TenantAuditAction,
    UserTenantSyncTrigger,
)
from bisheng.tenant.domain.services import user_tenant_sync_service as uts_module
from bisheng.tenant.domain.services.user_tenant_sync_service import (
    UserTenantSyncService,
)


def _tenant(tid, status='active'):
    return SimpleNamespace(
        id=tid, tenant_code=f't{tid}', tenant_name=f'T{tid}',
        parent_tenant_id=None if tid == 1 else 1,
        status=status, share_default_to_children=True,
    )


def _user_tenant(user_id, tenant_id):
    return SimpleNamespace(user_id=user_id, tenant_id=tenant_id, is_active=1)


@pytest.fixture()
def patches(monkeypatch):
    """One fixture wires up every collaborator the service touches."""
    resolver_mock = AsyncMock(name='resolve_user_leaf_tenant')
    active_mock = AsyncMock(name='aget_active_user_tenant')
    activate_mock = AsyncMock(name='aactivate_user_tenant')
    increment_mock = AsyncMock(name='aincrement_token_version')
    batch_tuples_mock = AsyncMock(name='batch_write_tuples')
    audit_mock = AsyncMock(name='ainsert_v2')
    count_mock = AsyncMock(name='_count_owned_resources')
    invalidate_mock = AsyncMock(name='_invalidate_redis_caches')
    notify_mock = AsyncMock(name='_notify_resource_owner_relocation')

    monkeypatch.setattr(
        uts_module.TenantResolver, 'resolve_user_leaf_tenant', resolver_mock,
    )
    monkeypatch.setattr(
        uts_module.UserTenantDao, 'aget_active_user_tenant', active_mock,
    )
    monkeypatch.setattr(
        uts_module.UserTenantDao, 'aactivate_user_tenant', activate_mock,
    )
    monkeypatch.setattr(
        uts_module.UserDao, 'aincrement_token_version', increment_mock,
    )
    monkeypatch.setattr(
        uts_module.PermissionService, 'batch_write_tuples', batch_tuples_mock,
    )
    monkeypatch.setattr(
        uts_module.AuditLogDao, 'ainsert_v2', audit_mock,
    )
    monkeypatch.setattr(
        uts_module.UserTenantSyncService, '_count_owned_resources', count_mock,
    )
    monkeypatch.setattr(
        uts_module.UserTenantSyncService, '_invalidate_redis_caches', invalidate_mock,
    )
    monkeypatch.setattr(
        uts_module.UserTenantSyncService,
        '_notify_resource_owner_relocation', notify_mock,
    )

    return SimpleNamespace(
        resolve=resolver_mock,
        get_active=active_mock,
        activate=activate_mock,
        increment=increment_mock,
        batch_tuples=batch_tuples_mock,
        audit=audit_mock,
        count_owned=count_mock,
        invalidate=invalidate_mock,
        notify=notify_mock,
    )


def _set_enforce(monkeypatch, value: bool):
    """Patch ``_enforce_transfer_before_relocate`` classmethod directly —
    avoids touching the deep ``bisheng.common.services.config_service``
    (pre-mocked in conftest)."""
    monkeypatch.setattr(
        uts_module.UserTenantSyncService,
        '_enforce_transfer_before_relocate',
        classmethod(lambda cls: value),
    )


# -------------------------------------------------------------------------
# No-op branch
# -------------------------------------------------------------------------

class TestNoChange:

    def test_same_leaf_returns_early(self, patches, monkeypatch):
        _set_enforce(monkeypatch, False)
        patches.resolve.return_value = _tenant(5)
        patches.get_active.return_value = _user_tenant(100, 5)

        result = asyncio.run(UserTenantSyncService.sync_user(100))
        assert result.id == 5
        patches.activate.assert_not_awaited()
        patches.increment.assert_not_awaited()
        patches.batch_tuples.assert_not_awaited()
        patches.audit.assert_not_awaited()


# -------------------------------------------------------------------------
# Relocate — happy path
# -------------------------------------------------------------------------

class TestRelocateHappy:

    def test_swap_flow_calls_all_collaborators(self, patches, monkeypatch):
        _set_enforce(monkeypatch, False)
        patches.resolve.return_value = _tenant(7)
        patches.get_active.return_value = _user_tenant(100, 5)
        patches.count_owned.return_value = 0

        result = asyncio.run(UserTenantSyncService.sync_user(
            100, trigger=UserTenantSyncTrigger.DEPT_CHANGE,
        ))
        assert result.id == 7
        patches.activate.assert_awaited_once_with(100, 7)
        patches.increment.assert_awaited_once_with(100)
        patches.batch_tuples.assert_awaited_once()
        patches.invalidate.assert_awaited_once_with(100)

        # audit_log.action = user.tenant_relocated
        audit_kwargs = patches.audit.call_args.kwargs
        assert audit_kwargs['action'] == TenantAuditAction.USER_TENANT_RELOCATED.value
        assert audit_kwargs['metadata']['old_tenant_id'] == 5
        assert audit_kwargs['metadata']['new_tenant_id'] == 7
        assert audit_kwargs['metadata']['owned_count'] == 0
        assert audit_kwargs['metadata']['trigger'] == 'dept_change'

        # No inbox notice when owned_count == 0.
        patches.notify.assert_not_awaited()

    def test_warns_but_proceeds_when_owned_resources_exist(
        self, patches, monkeypatch,
    ):
        _set_enforce(monkeypatch, False)
        patches.resolve.return_value = _tenant(7)
        patches.get_active.return_value = _user_tenant(101, 5)
        patches.count_owned.return_value = 3

        result = asyncio.run(UserTenantSyncService.sync_user(
            101, trigger=UserTenantSyncTrigger.DEPT_CHANGE,
        ))
        assert result.id == 7

        # Swap happened.
        patches.activate.assert_awaited_once_with(101, 7)
        patches.increment.assert_awaited_once_with(101)

        # Audit relocated written with owned_count=3.
        audit_kwargs = patches.audit.call_args.kwargs
        assert audit_kwargs['action'] == TenantAuditAction.USER_TENANT_RELOCATED.value
        assert audit_kwargs['metadata']['owned_count'] == 3

        # Inbox notification fired.
        patches.notify.assert_awaited_once()

    def test_fga_rewrite_revokes_old_and_writes_new(
        self, patches, monkeypatch,
    ):
        _set_enforce(monkeypatch, False)
        patches.resolve.return_value = _tenant(7)
        patches.get_active.return_value = _user_tenant(102, 5)
        patches.count_owned.return_value = 0

        asyncio.run(UserTenantSyncService.sync_user(102))

        args, kwargs = patches.batch_tuples.call_args
        ops = args[0]
        # One delete for tenant:5, one write for tenant:7.
        assert len(ops) == 2
        delete_op = next(o for o in ops if o.action == 'delete')
        write_op = next(o for o in ops if o.action == 'write')
        assert delete_op.object == 'tenant:5'
        assert delete_op.relation == 'member'
        assert delete_op.user == 'user:102'
        assert write_op.object == 'tenant:7'
        assert write_op.relation == 'member'
        assert kwargs.get('crash_safe') is True

    def test_skip_fga_write_for_root_leaf(self, patches, monkeypatch):
        """INV-T3: Root does not carry tenant:1#member tuples."""
        _set_enforce(monkeypatch, False)
        patches.resolve.return_value = _tenant(1)
        patches.get_active.return_value = _user_tenant(103, 5)
        patches.count_owned.return_value = 0

        asyncio.run(UserTenantSyncService.sync_user(103))

        args, kwargs = patches.batch_tuples.call_args
        ops = args[0]
        # Only a delete for the old tenant; no write for Root.
        assert len(ops) == 1
        assert ops[0].action == 'delete'
        assert ops[0].object == 'tenant:5'


# -------------------------------------------------------------------------
# Enforce-transfer-before-relocate branch
# -------------------------------------------------------------------------

class TestBlocked:

    def test_blocked_when_owned_and_enforce_true(self, patches, monkeypatch):
        _set_enforce(monkeypatch, True)
        patches.resolve.return_value = _tenant(7)
        patches.get_active.return_value = _user_tenant(200, 5)
        patches.count_owned.return_value = 2

        with pytest.raises(TenantRelocateBlockedError):
            asyncio.run(UserTenantSyncService.sync_user(
                200, trigger=UserTenantSyncTrigger.DEPT_CHANGE,
            ))

        # Blocked audit written.
        audit_kwargs = patches.audit.call_args.kwargs
        assert audit_kwargs['action'] == TenantAuditAction.USER_TENANT_RELOCATE_BLOCKED.value
        assert audit_kwargs['metadata']['owned_count'] == 2

        # No swap / no token bump / no FGA writes.
        patches.activate.assert_not_awaited()
        patches.increment.assert_not_awaited()
        patches.batch_tuples.assert_not_awaited()

    def test_not_blocked_when_enforce_true_but_no_owned_resources(
        self, patches, monkeypatch,
    ):
        _set_enforce(monkeypatch, True)
        patches.resolve.return_value = _tenant(7)
        patches.get_active.return_value = _user_tenant(201, 5)
        patches.count_owned.return_value = 0

        result = asyncio.run(UserTenantSyncService.sync_user(201))
        assert result.id == 7
        patches.activate.assert_awaited_once_with(201, 7)


# -------------------------------------------------------------------------
# First-time sync (no prior active row)
# -------------------------------------------------------------------------

class TestFirstTimeSync:

    def test_no_active_row_no_count_no_delete(self, patches, monkeypatch):
        _set_enforce(monkeypatch, False)
        patches.resolve.return_value = _tenant(7)
        patches.get_active.return_value = None

        asyncio.run(UserTenantSyncService.sync_user(300))

        # count_owned must NOT be awaited (no old tenant to count under).
        patches.count_owned.assert_not_awaited()

        # FGA ops: only one write for the new leaf, no delete.
        args, _ = patches.batch_tuples.call_args
        ops = args[0]
        assert len(ops) == 1
        assert ops[0].action == 'write'
        assert ops[0].object == 'tenant:7'

    def test_first_time_sync_root_writes_no_audit_reason_set(
        self, patches, monkeypatch,
    ):
        """User has no primary department → resolver returns Root; audit
        metadata records ``reason='no_primary_department'``."""
        _set_enforce(monkeypatch, False)
        patches.resolve.return_value = _tenant(1)  # Root
        patches.get_active.return_value = None

        asyncio.run(UserTenantSyncService.sync_user(301))

        audit_kwargs = patches.audit.call_args.kwargs
        assert audit_kwargs['reason'] == 'no_primary_department'


# -------------------------------------------------------------------------
# FGA failure tolerance
# -------------------------------------------------------------------------

class TestFgaTolerance:

    def test_fga_exception_does_not_abort_sync(self, patches, monkeypatch):
        _set_enforce(monkeypatch, False)
        patches.resolve.return_value = _tenant(7)
        patches.get_active.return_value = _user_tenant(400, 5)
        patches.count_owned.return_value = 0
        patches.batch_tuples.side_effect = RuntimeError('fga down')

        # Should NOT raise — fail-open behaviour per spec.
        result = asyncio.run(UserTenantSyncService.sync_user(400))
        assert result.id == 7

        # DB swap + token bump + audit still completed.
        patches.activate.assert_awaited_once()
        patches.increment.assert_awaited_once()
        patches.audit.assert_awaited_once()
