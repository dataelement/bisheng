"""F019 T09 — verify ``UserTenantSyncService.sync_user`` clears admin-scope
after a successful relocation (token_version +1).

Two cases:
  - AC-11 happy path: cross-tenant relocation → ``clear_on_token_version_bump``
    awaited exactly once with the user's id.
  - Same-tenant no-op path: new_leaf == current_leaf → the whole relocation
    block is skipped, so the scope clear must NOT be invoked.

This is a wiring test — service internals (FGA tuples, audit payload) are
covered by F012's suite; here we only assert the hook fires.
"""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


SERVICE_MOD = 'bisheng.tenant.domain.services.user_tenant_sync_service'


def _patch_deps(monkeypatch, new_leaf_id: int, current_leaf_id=None):
    """Patch every collaborator ``sync_user`` touches.

    - ``TenantResolver.resolve_user_leaf_tenant`` returns a fake Tenant.
    - ``UserTenantDao`` / ``UserDao`` DAO calls become AsyncMocks.
    - ``PermissionService.batch_write_tuples`` becomes AsyncMock.
    - ``AuditLogDao.ainsert_v2`` becomes AsyncMock.
    - The F019 ``TenantScopeService`` module is inserted into sys.modules
      so the late import inside the service resolves to our spy.
    """
    import importlib
    mod = importlib.import_module(SERVICE_MOD)

    fake_leaf = SimpleNamespace(id=new_leaf_id)
    monkeypatch.setattr(
        mod.TenantResolver, 'resolve_user_leaf_tenant',
        AsyncMock(return_value=fake_leaf),
    )

    # Current leaf — None for first-time, or SimpleNamespace with tenant_id.
    current = (
        None if current_leaf_id is None
        else SimpleNamespace(tenant_id=current_leaf_id)
    )
    monkeypatch.setattr(
        mod.UserTenantDao, 'aget_active_user_tenant',
        AsyncMock(return_value=current),
    )
    monkeypatch.setattr(
        mod.UserTenantDao, 'aactivate_user_tenant',
        AsyncMock(),
    )
    monkeypatch.setattr(
        mod.UserDao, 'aincrement_token_version', AsyncMock(return_value=1),
    )
    monkeypatch.setattr(
        mod.PermissionService, 'batch_write_tuples', AsyncMock(),
    )
    monkeypatch.setattr(
        mod.AuditLogDao, 'ainsert_v2', AsyncMock(),
    )
    # The owned-resource COUNT path opens a DB session we don't want; stub
    # the private counter directly.
    monkeypatch.setattr(
        mod.UserTenantSyncService, '_count_owned_resources',
        AsyncMock(return_value=0),
    )
    # Skip the Redis cache eviction — its own path is covered elsewhere.
    monkeypatch.setattr(
        mod.UserTenantSyncService, '_invalidate_redis_caches',
        AsyncMock(),
    )

    # Install fake TenantScopeService — the service uses a local import, so
    # we inject it through sys.modules.
    clear_mock = AsyncMock()
    fake_ts_mod = MagicMock()
    fake_ts_mod.TenantScopeService = MagicMock()
    fake_ts_mod.TenantScopeService.clear_on_token_version_bump = clear_mock
    sys.modules['bisheng.admin.domain.services.tenant_scope'] = fake_ts_mod

    return mod, clear_mock


def test_cross_tenant_relocation_clears_scope(monkeypatch):
    """AC-11: user moves 5 → 7 → ``clear_on_token_version_bump(user_id)``."""
    mod, clear_mock = _patch_deps(monkeypatch, new_leaf_id=7, current_leaf_id=5)

    asyncio.run(mod.UserTenantSyncService.sync_user(user_id=42))

    clear_mock.assert_awaited_once_with(42)


def test_same_tenant_noop_does_not_clear_scope(monkeypatch):
    """No-relocation exit must not touch the scope."""
    mod, clear_mock = _patch_deps(monkeypatch, new_leaf_id=5, current_leaf_id=5)

    asyncio.run(mod.UserTenantSyncService.sync_user(user_id=42))

    clear_mock.assert_not_awaited()


def test_scope_clear_failure_does_not_break_relocation(monkeypatch):
    """A Redis outage on scope clear must NOT prevent the relocation from
    returning the new leaf tenant (audit_log has already recorded it)."""
    mod, clear_mock = _patch_deps(monkeypatch, new_leaf_id=7, current_leaf_id=5)
    clear_mock.side_effect = RuntimeError('redis down')

    result = asyncio.run(mod.UserTenantSyncService.sync_user(user_id=42))

    assert result.id == 7
    clear_mock.assert_awaited_once_with(42)
