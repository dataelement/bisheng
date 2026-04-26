"""Tests for UserTenantSyncService.sync_subtree_primary_users.

Covers the batch backfill helper invoked from mount/unmount/move events.
DAO + sync_user are mocked; the contract under test is:

  - subtree dept ids resolved via DepartmentDao.aget_subtree_ids(path)
  - per-dept primary user ids resolved via
    UserDepartmentDao.aget_user_ids_by_department(id, is_primary=True)
  - duplicate user ids deduped before fan-out
  - per-user sync_user failures collected, never propagate
  - empty path / empty subtree / empty user set short-circuit cleanly
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from bisheng.tenant.domain.constants import UserTenantSyncTrigger
from bisheng.tenant.domain.services import user_tenant_sync_service as uts_module
from bisheng.tenant.domain.services.user_tenant_sync_service import (
    UserTenantSyncService,
)


@pytest.fixture()
def patches(monkeypatch):
    subtree_mock = AsyncMock(name='aget_subtree_ids')
    users_mock = AsyncMock(name='aget_user_ids_by_department')
    sync_mock = AsyncMock(name='sync_user')

    monkeypatch.setattr(
        uts_module.DepartmentDao, 'aget_subtree_ids', subtree_mock,
    )
    monkeypatch.setattr(
        uts_module.UserDepartmentDao, 'aget_user_ids_by_department', users_mock,
    )
    monkeypatch.setattr(
        uts_module.UserTenantSyncService, 'sync_user', sync_mock,
    )

    class _P:
        pass

    p = _P()
    p.subtree = subtree_mock
    p.users = users_mock
    p.sync = sync_mock
    return p


@pytest.mark.asyncio
class TestSyncSubtreePrimaryUsers:

    async def test_empty_path_short_circuits(self, patches):
        result = await UserTenantSyncService.sync_subtree_primary_users(
            dept_path='', trigger=UserTenantSyncTrigger.MOUNT_BACKFILL,
        )
        assert result == {'synced': [], 'failed': []}
        patches.subtree.assert_not_awaited()
        patches.users.assert_not_awaited()
        patches.sync.assert_not_awaited()

    async def test_empty_subtree_short_circuits(self, patches):
        patches.subtree.return_value = []
        result = await UserTenantSyncService.sync_subtree_primary_users(
            dept_path='/1/9/', trigger=UserTenantSyncTrigger.MOUNT_BACKFILL,
        )
        assert result == {'synced': [], 'failed': []}
        patches.users.assert_not_awaited()
        patches.sync.assert_not_awaited()

    async def test_dedup_users_across_depts(self, patches):
        """Same user id across two depts in the subtree must be synced once."""
        patches.subtree.return_value = [7, 12]

        async def _users_per_dept(dept_id, is_primary=None):
            return {7: [101, 102], 12: [102, 103]}[dept_id]

        patches.users.side_effect = _users_per_dept

        result = await UserTenantSyncService.sync_subtree_primary_users(
            dept_path='/1/7/', trigger=UserTenantSyncTrigger.MOUNT_BACKFILL,
        )

        assert sorted(result['synced']) == [101, 102, 103]
        assert result['failed'] == []
        # sync_user invoked exactly 3 times (deduped 102)
        assert patches.sync.await_count == 3
        # is_primary=True on every users-by-dept call
        for call in patches.users.await_args_list:
            assert call.kwargs.get('is_primary') is True

    async def test_per_user_failure_does_not_stop_others(self, patches):
        patches.subtree.return_value = [7]
        patches.users.return_value = [101, 102, 103]

        async def _sync(user_id, *, trigger):
            if user_id == 102:
                raise RuntimeError('relocate blocked')
            return None

        patches.sync.side_effect = _sync

        result = await UserTenantSyncService.sync_subtree_primary_users(
            dept_path='/1/7/', trigger=UserTenantSyncTrigger.UNMOUNT_REDERIVE,
        )

        assert sorted(result['synced']) == [101, 103]
        assert len(result['failed']) == 1
        assert result['failed'][0][0] == 102
        assert 'relocate blocked' in result['failed'][0][1]
        assert patches.sync.await_count == 3

    async def test_trigger_is_passed_through(self, patches):
        patches.subtree.return_value = [7]
        patches.users.return_value = [101]
        await UserTenantSyncService.sync_subtree_primary_users(
            dept_path='/1/7/', trigger=UserTenantSyncTrigger.DEPT_MOVED,
        )
        patches.sync.assert_awaited_once_with(
            101, trigger=UserTenantSyncTrigger.DEPT_MOVED,
        )

    async def test_dept_with_no_users_skipped(self, patches):
        """A subtree where every dept returns [] yields synced/failed both empty."""
        patches.subtree.return_value = [7, 12, 19]
        patches.users.return_value = []

        result = await UserTenantSyncService.sync_subtree_primary_users(
            dept_path='/1/7/', trigger=UserTenantSyncTrigger.MOUNT_BACKFILL,
        )

        assert result == {'synced': [], 'failed': []}
        # users mock called once per dept
        assert patches.users.await_count == 3
        patches.sync.assert_not_awaited()
