"""Tests for batched user-tenant drift detection."""

from unittest.mock import AsyncMock

import pytest

from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
from bisheng.database.models.tenant import TenantDao, UserTenantDao
from bisheng.tenant.domain.services.user_tenant_reconcile_service import (
    UserTenantReconcileContext,
    UserTenantReconcileService,
)


def _context(
    mounts: dict[int, int] | None = None,
    active_tenants: set[int] | None = None,
) -> UserTenantReconcileContext:
    return UserTenantReconcileContext(
        mount_tenant_by_department=mounts or {},
        active_tenant_ids=frozenset(active_tenants or {1}),
    )


class TestExpectedTenantId:
    def test_no_primary_department_falls_back_to_root(self):
        assert UserTenantReconcileService.expected_tenant_id(None, _context()) == 1

    def test_nearest_active_mount_wins(self):
        context = _context(mounts={2: 20, 5: 50}, active_tenants={1, 20, 50})

        tenant_id = UserTenantReconcileService.expected_tenant_id(
            (9, "/1/2/5/9/"),
            context,
        )

        assert tenant_id == 50

    def test_disabled_nearest_mount_falls_back_to_active_ancestor(self):
        context = _context(mounts={2: 20, 5: 50}, active_tenants={1, 20})

        tenant_id = UserTenantReconcileService.expected_tenant_id(
            (9, "/1/2/5/9/"),
            context,
        )

        assert tenant_id == 20

    def test_primary_id_missing_from_path_is_still_checked(self):
        context = _context(mounts={9: 90}, active_tenants={1, 90})

        tenant_id = UserTenantReconcileService.expected_tenant_id(
            (9, "/1/2/"),
            context,
        )

        assert tenant_id == 90


@pytest.mark.asyncio
async def test_load_context_batches_topology(monkeypatch):
    mounts = AsyncMock(return_value={10: 100})
    tenants = AsyncMock(return_value={1, 100})
    monkeypatch.setattr(DepartmentDao, "aget_mount_tenant_ids", mounts)
    monkeypatch.setattr(TenantDao, "aget_active_ids", tenants)

    context = await UserTenantReconcileService.load_context()

    assert context.mount_tenant_by_department == {10: 100}
    assert context.active_tenant_ids == frozenset({1, 100})


@pytest.mark.asyncio
async def test_find_drifted_users_uses_two_batch_queries(monkeypatch):
    primary = AsyncMock(
        return_value={
            1: (9, "/1/2/9/"),
            2: (5, "/1/5/"),
        }
    )
    current = AsyncMock(return_value={1: 20, 2: 1})
    monkeypatch.setattr(
        UserDepartmentDao,
        "aget_primary_department_paths_by_user_ids",
        primary,
    )
    monkeypatch.setattr(
        UserTenantDao,
        "aget_active_tenant_ids_by_user_ids",
        current,
    )
    context = _context(mounts={2: 20}, active_tenants={1, 20})

    drifted = await UserTenantReconcileService.find_drifted_user_ids(
        [1, 2, 3],
        context,
    )

    assert drifted == [3]
    primary.assert_awaited_once_with([1, 2, 3])
    current.assert_awaited_once_with([1, 2, 3])
