"""Tests for F012 UserDepartmentService.change_primary_department.

All DAO / DB / sync_user interactions are mocked — this suite validates
orchestration (no-op branch, demote+promote order, sync_user invocation
with DEPT_CHANGE trigger, propagation of TenantRelocateBlockedError).
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.common.errcode.tenant_resolver import TenantRelocateBlockedError
from bisheng.tenant.domain.constants import UserTenantSyncTrigger
from bisheng.user.domain.services import user_department_service as uds_module
from bisheng.user.domain.services.user_department_service import (
    UserDepartmentService,
)


def _primary(user_id: int, dept_id: int):
    return SimpleNamespace(
        user_id=user_id, department_id=dept_id, is_primary=1,
    )


@pytest.fixture()
def patches(monkeypatch):
    """Wire up the DAO / session / sync_user mocks."""
    primary_mock = AsyncMock(name='aget_user_primary_department')
    sync_mock = AsyncMock(name='sync_user')

    monkeypatch.setattr(
        uds_module.UserDepartmentDao,
        'aget_user_primary_department',
        primary_mock,
    )
    monkeypatch.setattr(
        uds_module.UserTenantSyncService, 'sync_user', sync_mock,
    )
    dept_execute = AsyncMock(name='DepartmentChangeHandler.execute_async')
    monkeypatch.setattr(
        uds_module.DepartmentChangeHandler, 'execute_async', dept_execute,
    )

    # Fake async session — record every ``exec`` + ``add`` + ``commit``.
    session_calls = {
        'exec': [], 'add': [], 'commit': 0,
    }

    class _FakeExecResult:
        def __init__(self, rows=()):
            self._rows = list(rows)

        def first(self):
            return self._rows[0] if self._rows else None

    # By default `exec(select(...))` returns no secondary row. Callers that
    # want a different shape can replace this list's first element via
    # ``session_calls['exec_result'] = [row]`` before calling the service.
    exec_result = []
    session_calls['exec_result'] = exec_result

    class _FakeSession:
        async def exec(self, stmt):
            session_calls['exec'].append(stmt)
            if session_calls['exec_result']:
                return _FakeExecResult(
                    [session_calls['exec_result'].pop(0)]
                )
            return _FakeExecResult([])

        def add(self, obj):
            session_calls['add'].append(obj)

        async def commit(self):
            session_calls['commit'] += 1

    @asynccontextmanager
    async def _fake_get_session():
        yield _FakeSession()

    monkeypatch.setattr(uds_module, 'get_async_db_session', _fake_get_session)

    return SimpleNamespace(
        primary=primary_mock,
        sync=sync_mock,
        dept_execute=dept_execute,
        session_calls=session_calls,
    )


# -------------------------------------------------------------------------
# No-op branch
# -------------------------------------------------------------------------

class TestNoOp:

    def test_same_primary_skips_writes_and_sync(self, patches):
        patches.primary.return_value = _primary(100, 5)

        result = asyncio.run(
            UserDepartmentService.change_primary_department(100, 5)
        )
        assert result['changed'] is False
        patches.sync.assert_not_awaited()
        patches.dept_execute.assert_not_awaited()
        assert patches.session_calls['commit'] == 0


# -------------------------------------------------------------------------
# Happy path — swap + sync
# -------------------------------------------------------------------------

class TestHappyPath:

    def test_promote_new_primary_triggers_sync(self, patches):
        patches.primary.return_value = _primary(100, 5)
        patches.sync.return_value = SimpleNamespace(id=7)

        result = asyncio.run(
            UserDepartmentService.change_primary_department(100, 12)
        )
        assert result['changed'] is True
        assert result['primary_department_id'] == 12
        assert result['leaf_tenant_id'] == 7

        # sync_user called with DEPT_CHANGE trigger.
        patches.sync.assert_awaited_once()
        call = patches.sync.call_args
        assert call.args[0] == 100
        assert call.kwargs.get('trigger') == UserTenantSyncTrigger.DEPT_CHANGE

        # DB writes happened (1 commit).
        assert patches.session_calls['commit'] == 1
        patches.dept_execute.assert_awaited_once()
        ops = patches.dept_execute.await_args.args[0]
        assert [(op.action, op.user, op.relation, op.object) for op in ops] == [
            ('write', 'user:100', 'member', 'department:12'),
        ]

    def test_first_primary_no_demote(self, patches):
        """No existing primary → just insert a row and sync."""
        patches.primary.return_value = None
        patches.sync.return_value = SimpleNamespace(id=1)

        result = asyncio.run(
            UserDepartmentService.change_primary_department(101, 20)
        )
        assert result['changed'] is True
        patches.sync.assert_awaited_once()


# -------------------------------------------------------------------------
# Blocked propagation
# -------------------------------------------------------------------------

class TestBlockedPropagation:

    def test_sync_blocked_raises(self, patches):
        patches.primary.return_value = _primary(102, 5)
        patches.sync.side_effect = TenantRelocateBlockedError(
            owned_count=3,
        )

        with pytest.raises(TenantRelocateBlockedError):
            asyncio.run(
                UserDepartmentService.change_primary_department(102, 12)
            )


# -------------------------------------------------------------------------
# Trigger passthrough (explicit regression)
# -------------------------------------------------------------------------

class TestTriggerEnumUsed:

    def test_trigger_value_is_dept_change(self, patches):
        patches.primary.return_value = _primary(103, 5)
        patches.sync.return_value = SimpleNamespace(id=7)

        asyncio.run(
            UserDepartmentService.change_primary_department(103, 12)
        )
        trigger = patches.sync.call_args.kwargs.get('trigger')
        assert trigger == UserTenantSyncTrigger.DEPT_CHANGE
        assert trigger.value == 'dept_change'
