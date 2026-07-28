from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng.department.domain.services.department_sync_rbac_service import (
    DepartmentSyncRBACService,
)


@pytest.mark.asyncio
async def test_revoke_only_roles_scoped_to_departure_department(monkeypatch):
    module = __import__(
        "bisheng.department.domain.services.department_sync_rbac_service",
        fromlist=["DepartmentSyncRBACService"],
    )
    monkeypatch.setattr(
        module.UserRoleDao,
        "aget_user_roles",
        AsyncMock(
            return_value=[
                SimpleNamespace(role_id=2),
                SimpleNamespace(role_id=10),
                SimpleNamespace(role_id=11),
            ]
        ),
    )
    monkeypatch.setattr(
        module.RoleDao,
        "aget_role_by_ids",
        AsyncMock(
            return_value=[
                SimpleNamespace(id=2, department_id=None),
                SimpleNamespace(id=10, department_id=100),
                SimpleNamespace(id=11, department_id=200),
            ]
        ),
    )
    delete_roles = Mock()
    monkeypatch.setattr(module.UserRoleDao, "delete_user_roles", delete_roles)
    sync_roles = AsyncMock()
    monkeypatch.setattr(
        module.LegacyRBACSyncService,
        "sync_user_role_change",
        sync_roles,
    )

    await DepartmentSyncRBACService.arevoke_user_roles_in_department(7, 100)

    delete_roles.assert_called_once_with(7, [10])
    sync_roles.assert_awaited_once_with(7, {2, 10, 11}, {2, 11})


@pytest.mark.asyncio
async def test_apply_only_valid_defaults_scoped_to_target_department(monkeypatch):
    module = __import__(
        "bisheng.department.domain.services.department_sync_rbac_service",
        fromlist=["DepartmentSyncRBACService"],
    )
    monkeypatch.setattr(
        module.DepartmentDao,
        "aget_by_id",
        AsyncMock(
            return_value=SimpleNamespace(
                id=100,
                path="/1/",
                status="active",
                default_role_ids=[1, 10, 11, 12],
            )
        ),
    )
    monkeypatch.setattr(
        module.RoleDao,
        "aget_role_by_ids",
        AsyncMock(
            return_value=[
                SimpleNamespace(id=10, department_id=100),
                SimpleNamespace(id=11, department_id=200),
                SimpleNamespace(id=12, department_id=None),
            ]
        ),
    )
    monkeypatch.setattr(
        module.UserRoleDao,
        "aget_user_roles",
        AsyncMock(return_value=[SimpleNamespace(role_id=2)]),
    )
    add_roles = Mock()
    monkeypatch.setattr(module.UserRoleDao, "add_user_roles", add_roles)
    sync_roles = AsyncMock()
    monkeypatch.setattr(
        module.LegacyRBACSyncService,
        "sync_user_role_change",
        sync_roles,
    )

    await DepartmentSyncRBACService.aapply_department_default_roles_for_user(7, 100)

    add_roles.assert_called_once_with(7, [10, 12])
    sync_roles.assert_awaited_once_with(7, {2}, {2, 10, 12})
