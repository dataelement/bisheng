"""SSO revoke paths must clean the department-admin knowledge-space binding.

``LoginSyncService._sync_department_admin_tuples`` (leader-list reconcile) and
``_remove_department_membership`` previously dropped only the
``DepartmentAdminGrant`` row + the ``department#admin`` tuple. The derived
``space_channel_member`` row and ``knowledge_space#manager`` tuple were left
behind, so a user kept manage access to the department's knowledge space after
SSO sync revoked their admin role (越权 residue).

Collaborators are AsyncMock'd — this suite asserts the cleanup invocation, not
DB / FGA behaviour.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.sso_sync.domain.services import login_sync_service as mod
from bisheng.sso_sync.domain.services.login_sync_service import LoginSyncService


@pytest.fixture()
def space_cleanup(monkeypatch):
    """Patch the lazy-imported binding cleanup on its source class."""
    from bisheng.knowledge.domain.services import (
        department_knowledge_space_service as ks_module,
    )

    cleanup = AsyncMock(name="cleanup_removed_department_admins")
    monkeypatch.setattr(
        ks_module.DepartmentKnowledgeSpaceService,
        "cleanup_removed_department_admins",
        cleanup,
    )
    return cleanup


def test_remove_department_membership_cleans_space_binding(monkeypatch, space_cleanup):
    """Removing a (secondary) membership revokes admin → must clean its space binding."""
    monkeypatch.setattr(mod.UserDepartmentDao, "aremove_member", AsyncMock())
    monkeypatch.setattr(mod.DepartmentChangeHandler, "execute_async", AsyncMock())
    monkeypatch.setattr(mod.DepartmentAdminGrantDao, "adelete", AsyncMock())

    asyncio.run(LoginSyncService._remove_department_membership(7, 5))

    space_cleanup.assert_awaited_once()
    _, kwargs = space_cleanup.call_args
    assert kwargs.get("department_id") == 5
    assert list(kwargs.get("user_ids")) == [7]


def test_admin_tuples_reconcile_cleans_revoked_dept_binding(monkeypatch, space_cleanup):
    """Leader-list reconcile that drops an SSO admin grant must clean its space binding."""
    membership = SimpleNamespace(department_id=5, is_primary=0)
    dept = SimpleNamespace(id=5, source="sso", external_id="D5", status="active")
    grant = SimpleNamespace(
        department_id=5,
        grant_source=mod.DEPARTMENT_ADMIN_GRANT_SOURCE_SSO,
    )

    monkeypatch.setattr(
        mod.UserDepartmentDao,
        "aget_user_departments",
        AsyncMock(return_value=[membership]),
    )
    monkeypatch.setattr(mod.DepartmentDao, "aget_by_ids", AsyncMock(return_value=[dept]))
    monkeypatch.setattr(
        mod.DepartmentAdminGrantDao,
        "aget_by_user_and_departments",
        AsyncMock(return_value=[grant]),
    )
    monkeypatch.setattr(mod.DepartmentAdminGrantDao, "adelete", AsyncMock())
    monkeypatch.setattr(mod.DepartmentChangeHandler, "execute_async", AsyncMock())

    # want = [] (present but empty) → D5 not wanted → SSO grant revoked.
    asyncio.run(LoginSyncService._sync_department_admin_tuples(7, [], row_source="sso"))

    space_cleanup.assert_awaited_once()
    _, kwargs = space_cleanup.call_args
    assert kwargs.get("department_id") == 5
    assert list(kwargs.get("user_ids")) == [7]


def test_admin_tuples_reconcile_skips_when_nothing_revoked(monkeypatch, space_cleanup):
    """When the user stays an admin (dept still wanted), no binding cleanup runs."""
    membership = SimpleNamespace(department_id=5, is_primary=0)
    dept = SimpleNamespace(id=5, source="sso", external_id="D5", status="active")
    grant = SimpleNamespace(
        department_id=5,
        grant_source=mod.DEPARTMENT_ADMIN_GRANT_SOURCE_SSO,
    )

    monkeypatch.setattr(
        mod.UserDepartmentDao,
        "aget_user_departments",
        AsyncMock(return_value=[membership]),
    )
    monkeypatch.setattr(mod.DepartmentDao, "aget_by_ids", AsyncMock(return_value=[dept]))
    monkeypatch.setattr(
        mod.DepartmentAdminGrantDao,
        "aget_by_user_and_departments",
        AsyncMock(return_value=[grant]),
    )
    monkeypatch.setattr(mod.DepartmentAdminGrantDao, "adelete", AsyncMock())
    monkeypatch.setattr(mod.DepartmentAdminGrantDao, "aupsert", AsyncMock())
    monkeypatch.setattr(mod.DepartmentChangeHandler, "execute_async", AsyncMock())

    asyncio.run(LoginSyncService._sync_department_admin_tuples(7, ["D5"], row_source="sso"))

    space_cleanup.assert_not_awaited()
