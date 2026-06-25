"""Tests for ``DepartmentService._apply_local_primary_department_change``.

Regression: the UI "编辑成员 → 改主部门" path used to commit the UserDepartment
swap and dispatch FGA ``department:*`` tuples but never trigger
``UserTenantSyncService.sync_user``. Cross-tenant primary changes therefore
left ``user_tenant.tenant_id`` stale until the next login or the 6h reconcile,
and ``enforce_transfer_before_relocate`` could not block the operator at save
time. Fix: invoke ``sync_user`` with ``DEPT_CHANGE`` after the FGA dispatch.

DAO / DB / FGA interactions are mocked — this suite validates orchestration:
sync invocation, no-op short-circuit, FGA dispatch ordering, and propagation
of ``TenantRelocateBlockedError``.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.tenant_resolver import TenantRelocateBlockedError
from bisheng.department.domain.services import department_service as ds_module
from bisheng.department.domain.services.department_service import DepartmentService
from bisheng.tenant.domain.constants import UserTenantSyncTrigger
from bisheng.tenant.domain.services import user_tenant_sync_service as sync_module


def _ud(user_id: int, dept_id: int, is_primary: int):
    """Stand-in for ``UserDepartment`` rows returned by session.exec()."""
    return SimpleNamespace(
        user_id=user_id,
        department_id=dept_id,
        is_primary=is_primary,
        source='local',
    )


@pytest.fixture()
def patches(monkeypatch):
    """Wire DAO / session / sync_user mocks for the local-primary swap path."""
    sync_mock = AsyncMock(name='sync_user')
    monkeypatch.setattr(sync_module.UserTenantSyncService, 'sync_user', sync_mock)

    dept_execute = AsyncMock(name='DepartmentChangeHandler.execute_async')
    monkeypatch.setattr(
        ds_module.DepartmentChangeHandler, 'execute_async', dept_execute,
    )
    admin_grant_delete = AsyncMock(name='DepartmentAdminGrantDao.adelete')
    monkeypatch.setattr(
        ds_module.DepartmentAdminGrantDao, 'adelete', admin_grant_delete,
    )
    # Space-binding cleanup is lazy-imported inside the service; patch it on the
    # source class so the leaving-old-dept path can be asserted without DB/FGA.
    from bisheng.knowledge.domain.services import (
        department_knowledge_space_service as ks_module,
    )
    space_cleanup = AsyncMock(name='cleanup_removed_department_admins')
    monkeypatch.setattr(
        ks_module.DepartmentKnowledgeSpaceService,
        'cleanup_removed_department_admins',
        space_cleanup,
    )

    session_calls = {
        'exec': [], 'add': [], 'delete': [], 'commit': 0,
        # ``rows_for_select`` controls what the next ``session.exec(select(UserDepartment...))``
        # returns. Tests set it once before driving the service.
        'rows_for_select': [],
    }

    class _FakeExecResult:
        def __init__(self, rows):
            self._rows = list(rows)

        def all(self):
            return list(self._rows)

        def first(self):
            return self._rows[0] if self._rows else None

    class _FakeSession:
        async def exec(self, stmt):
            session_calls['exec'].append(stmt)
            return _FakeExecResult(session_calls['rows_for_select'])

        def add(self, obj):
            session_calls['add'].append(obj)

        async def delete(self, obj):
            session_calls['delete'].append(obj)

        async def commit(self):
            session_calls['commit'] += 1

    @asynccontextmanager
    async def _fake_get_session():
        yield _FakeSession()

    monkeypatch.setattr(ds_module, 'get_async_db_session', _fake_get_session)

    return SimpleNamespace(
        sync=sync_mock,
        dept_execute=dept_execute,
        admin_grant_delete=admin_grant_delete,
        space_cleanup=space_cleanup,
        session_calls=session_calls,
    )


# -------------------------------------------------------------------------
# No-op branch — same dept must not touch sync_user or DB
# -------------------------------------------------------------------------


def test_same_primary_dept_is_noop(patches):
    """Saving the same primary dept should short-circuit before any writes."""
    patches.session_calls['rows_for_select'] = [_ud(100, 5, is_primary=1)]

    asyncio.run(
        DepartmentService._apply_local_primary_department_change(100, 5)
    )

    patches.sync.assert_not_awaited()
    patches.dept_execute.assert_not_awaited()
    patches.admin_grant_delete.assert_not_awaited()
    patches.space_cleanup.assert_not_awaited()
    assert patches.session_calls['commit'] == 0
    assert patches.session_calls['delete'] == []
    assert patches.session_calls['add'] == []


# -------------------------------------------------------------------------
# No prior primary — first-time assignment
# -------------------------------------------------------------------------


def test_no_old_primary_inserts_and_syncs(patches):
    """First-time primary assignment: insert UserDepartment + dispatch FGA + sync."""
    patches.session_calls['rows_for_select'] = []  # user has no UserDepartment rows
    patches.sync.return_value = SimpleNamespace(id=7)

    asyncio.run(
        DepartmentService._apply_local_primary_department_change(101, 12)
    )

    # New UserDepartment row inserted (no delete — there was nothing to remove).
    assert patches.session_calls['delete'] == []
    inserted = [
        obj for obj in patches.session_calls['add']
        if hasattr(obj, 'department_id') and obj.department_id == 12
    ]
    assert len(inserted) == 1
    assert inserted[0].is_primary == 1
    assert inserted[0].source == 'local'
    assert patches.session_calls['commit'] == 1

    # FGA "member added" dispatched once (no removal — no old dept).
    patches.dept_execute.assert_awaited_once()
    patches.admin_grant_delete.assert_not_awaited()
    # No old dept → no department-admin binding to clean up.
    patches.space_cleanup.assert_not_awaited()

    # sync_user invoked with DEPT_CHANGE trigger.
    patches.sync.assert_awaited_once()
    args, kwargs = patches.sync.call_args
    assert args[0] == 101
    assert kwargs.get('trigger') == UserTenantSyncTrigger.DEPT_CHANGE


# -------------------------------------------------------------------------
# Cross-tenant swap — delete old primary, insert new, full FGA dispatch + sync
# -------------------------------------------------------------------------


def test_cross_tenant_swap_dispatches_fga_and_syncs(patches):
    """Move user from dept A (tenant a) → dept B (tenant b): delete old, insert new, sync."""
    patches.session_calls['rows_for_select'] = [_ud(102, 5, is_primary=1)]
    patches.sync.return_value = SimpleNamespace(id=8)

    asyncio.run(
        DepartmentService._apply_local_primary_department_change(102, 20)
    )

    # Old primary row deleted, new primary row inserted.
    assert len(patches.session_calls['delete']) == 1
    assert patches.session_calls['delete'][0].department_id == 5

    inserted = [
        obj for obj in patches.session_calls['add']
        if hasattr(obj, 'department_id') and obj.department_id == 20
    ]
    assert len(inserted) == 1
    assert inserted[0].is_primary == 1
    assert patches.session_calls['commit'] == 1

    # Two FGA dispatches: removal from old (member + admin), then add to new.
    assert patches.dept_execute.await_count == 2
    patches.admin_grant_delete.assert_awaited_once()
    grant_args, _ = patches.admin_grant_delete.call_args
    assert grant_args == (102, 5)

    # Leaving the old dept must clean the department-admin space binding
    # (space_channel_member row + knowledge_space#manager tuple) for that dept.
    patches.space_cleanup.assert_awaited_once()
    _, cleanup_kwargs = patches.space_cleanup.call_args
    assert cleanup_kwargs.get('department_id') == 5
    assert list(cleanup_kwargs.get('user_ids')) == [102]

    # sync_user invoked exactly once with DEPT_CHANGE.
    patches.sync.assert_awaited_once()
    args, kwargs = patches.sync.call_args
    assert args[0] == 102
    assert kwargs.get('trigger') == UserTenantSyncTrigger.DEPT_CHANGE


# -------------------------------------------------------------------------
# enforce_transfer_before_relocate=true: TenantRelocateBlockedError propagates
# -------------------------------------------------------------------------


def test_relocate_blocked_propagates(patches):
    """When sync_user blocks (enforce flag + owned resources), the error must
    bubble up so the API endpoint translates it to 409. DB writes are already
    committed at that point — that is the documented ordering caveat.
    """
    patches.session_calls['rows_for_select'] = [_ud(103, 5, is_primary=1)]
    patches.sync.side_effect = TenantRelocateBlockedError(
        owned_count=2, old_tenant_id=2, new_tenant_id=3,
    )

    with pytest.raises(TenantRelocateBlockedError):
        asyncio.run(
            DepartmentService._apply_local_primary_department_change(103, 20)
        )

    # DB swap + FGA dispatch did happen before sync_user raised.
    assert patches.session_calls['commit'] == 1
    assert patches.dept_execute.await_count == 2
    patches.sync.assert_awaited_once()
