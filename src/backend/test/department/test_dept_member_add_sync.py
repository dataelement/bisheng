"""Tests for G1/G2 fixes: tenant-sync coverage on dept member add paths.

G1 — ``DepartmentService.aadd_members(is_primary=1)``: primary-add now
routes through ``UserDepartmentService.change_primary_department`` per uid
so the user's old primary is demoted (no dual-primary) and
``UserTenantSyncService.sync_user`` is fired. ``is_primary=0`` keeps the
batch-insert + single FGA dispatch path with no sync (secondary adds don't
change the leaf tenant).

G2 — ``DepartmentService.acreate_local_member``: a brand-new user gets
``sync_user(DEPT_CHANGE)`` after the UserDepartment row is committed so
the user immediately appears in the tenant user list (which queries
UserTenant) instead of waiting for first login or the 6h reconcile.

DAO/DB/permission/RBAC interactions are mocked — these tests verify
orchestration only.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.common.errcode.tenant_resolver import TenantRelocateBlockedError
from bisheng.department.domain.services import department_service as ds_module
from bisheng.department.domain.services.department_service import DepartmentService
from bisheng.tenant.domain.constants import UserTenantSyncTrigger
from bisheng.tenant.domain.services import user_tenant_sync_service as sync_module
from bisheng.user.domain.services import user_department_service as uds_module


def _login_user(uid=1, tenant_id=1):
    return SimpleNamespace(user_id=uid, user_role=[], tenant_id=tenant_id)


def _dept(internal_id=10, dept_id='BS@hr', status='active'):
    return SimpleNamespace(
        id=internal_id,
        dept_id=dept_id,
        status=status,
        default_role_ids=[],
    )


# ===========================================================================
# G1: aadd_members
# ===========================================================================


@pytest.fixture()
def add_members_patches(monkeypatch):
    """Mocks for ``aadd_members`` orchestration tests."""
    dept = _dept()

    perm_mock = AsyncMock(name='_get_dept_and_check_permission', return_value=dept)
    monkeypatch.setattr(ds_module, '_get_dept_and_check_permission', perm_mock)

    grant_default_mock = AsyncMock(name='_grant_default_roles_to_users')
    monkeypatch.setattr(
        DepartmentService,
        '_grant_default_roles_to_users',
        classmethod(lambda cls, *a, **kw: grant_default_mock(*a, **kw)),
    )

    dept_execute = AsyncMock(name='DepartmentChangeHandler.execute_async')
    monkeypatch.setattr(
        ds_module.DepartmentChangeHandler, 'execute_async', dept_execute,
    )

    change_primary_mock = AsyncMock(
        name='UserDepartmentService.change_primary_department',
        return_value={'changed': True, 'leaf_tenant_id': 7},
    )
    monkeypatch.setattr(
        uds_module.UserDepartmentService,
        'change_primary_department',
        change_primary_mock,
    )

    session_calls = {
        'add': [], 'commit': 0, 'existing_user_ids': [],
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
            return _FakeExecResult(session_calls['existing_user_ids'])

        def add(self, obj):
            session_calls['add'].append(obj)

        async def commit(self):
            session_calls['commit'] += 1

    @asynccontextmanager
    async def _fake_get_session():
        yield _FakeSession()

    monkeypatch.setattr(ds_module, 'get_async_db_session', _fake_get_session)

    return SimpleNamespace(
        dept=dept,
        change_primary=change_primary_mock,
        dept_execute=dept_execute,
        grant_default=grant_default_mock,
        session_calls=session_calls,
    )


def test_aadd_members_secondary_path_skips_sync(add_members_patches):
    """is_primary=0 keeps the batch insert + FGA dispatch. No sync_user."""
    data = SimpleNamespace(user_ids=[101, 102, 103], is_primary=0)

    asyncio.run(
        DepartmentService.aadd_members('BS@hr', data, _login_user())
    )

    # Three UserDepartment rows inserted in a single commit.
    inserted_uids = [
        obj.user_id for obj in add_members_patches.session_calls['add']
        if hasattr(obj, 'user_id') and hasattr(obj, 'department_id')
    ]
    assert sorted(inserted_uids) == [101, 102, 103]
    assert add_members_patches.session_calls['commit'] == 1

    # Single batched FGA dispatch.
    add_members_patches.dept_execute.assert_awaited_once()

    # Primary path NOT used.
    add_members_patches.change_primary.assert_not_awaited()


def test_aadd_members_primary_path_routes_to_change_primary(add_members_patches):
    """is_primary=1 invokes change_primary_department per uid (no batch insert)."""
    data = SimpleNamespace(user_ids=[201, 202], is_primary=1)

    asyncio.run(
        DepartmentService.aadd_members('BS@hr', data, _login_user())
    )

    # No bulk insert in the validation session — each uid is handled by the
    # service which manages its own session.
    direct_inserts = [
        obj for obj in add_members_patches.session_calls['add']
        if hasattr(obj, 'user_id') and hasattr(obj, 'department_id')
    ]
    assert direct_inserts == []
    assert add_members_patches.session_calls['commit'] == 0

    # change_primary_department called per uid with the dept's internal id.
    assert add_members_patches.change_primary.await_count == 2
    seen_args = [
        call.args for call in add_members_patches.change_primary.await_args_list
    ]
    assert sorted(seen_args) == [(201, 10), (202, 10)]

    # Secondary-path FGA dispatch NOT used (the service emits its own per uid).
    add_members_patches.dept_execute.assert_not_awaited()


def test_aadd_members_primary_propagates_relocate_blocked(add_members_patches):
    """When change_primary_department raises (resource owner under old tenant),
    the error must bubble up so the API endpoint translates it to 409."""
    add_members_patches.change_primary.side_effect = TenantRelocateBlockedError(
        owned_count=3, old_tenant_id=2, new_tenant_id=4,
    )
    data = SimpleNamespace(user_ids=[301], is_primary=1)

    with pytest.raises(TenantRelocateBlockedError):
        asyncio.run(
            DepartmentService.aadd_members('BS@hr', data, _login_user())
        )

    add_members_patches.change_primary.assert_awaited_once()


# ===========================================================================
# G2: acreate_local_member
# ===========================================================================


def _async_return(value):
    async def _coro():
        return value
    return _coro()


@pytest.fixture()
def create_member_patches(monkeypatch):
    """Mocks for ``acreate_local_member`` — focuses on the sync trigger.

    ``acreate_local_member`` lazy-imports ``bisheng.user.domain.{models,services}.user``;
    those modules pull in ``rsa`` which isn't in the test env. We inject
    stub modules into ``sys.modules`` before the function reaches its
    imports so the real chain never loads.
    """
    import sys
    from types import ModuleType

    dept = _dept()
    fake_user = SimpleNamespace(user_id=555, user_name='alice')

    # ── Stub user module chain to avoid the real (rsa-dependent) imports ──
    user_dao = MagicMock(name='UserDao')
    user_dao.aget_login_candidates_by_account = AsyncMock(return_value=[])
    user_dao.aexists_disabled_login_account = AsyncMock(return_value=False)
    user_dao.add_user_with_groups_and_roles = MagicMock(return_value=fake_user)

    user_models_mod = ModuleType('bisheng.user.domain.models.user')
    user_models_mod.User = lambda **kw: SimpleNamespace(**kw)
    user_models_mod.UserDao = user_dao
    monkeypatch.setitem(
        sys.modules, 'bisheng.user.domain.models.user', user_models_mod,
    )

    user_service = MagicMock(name='UserService')
    user_service.decrypt_password_plain = MagicMock(return_value='Pa55word!aaaa')
    user_services_mod = ModuleType('bisheng.user.domain.services.user')
    user_services_mod.UserService = user_service
    monkeypatch.setitem(
        sys.modules, 'bisheng.user.domain.services.user', user_services_mod,
    )

    utils_mod = ModuleType('bisheng.utils')
    utils_mod.md5_hash = lambda s: 'pwhash'
    monkeypatch.setitem(sys.modules, 'bisheng.utils', utils_mod)

    # ── Mock the orchestration touchpoints ──
    perm_mock = AsyncMock(name='_get_dept_and_check_permission', return_value=dept)
    monkeypatch.setattr(ds_module, '_get_dept_and_check_permission', perm_mock)

    raise_mock = AsyncMock(name='_get_dept_or_raise', return_value=dept)
    monkeypatch.setattr(ds_module, '_get_dept_or_raise', raise_mock)

    monkeypatch.setattr(ds_module, '_password_meets_prd_policy', lambda _p: True)
    monkeypatch.setattr(
        DepartmentService,
        'aget_assignable_roles',
        classmethod(lambda cls, *a, **kw: _async_return([{'id': 99}])),
    )

    legacy_sync = MagicMock()
    legacy_sync.sync_user_auth_created = AsyncMock()
    monkeypatch.setattr(ds_module, 'LegacyRBACSyncService', legacy_sync)

    dept_execute = AsyncMock(name='DepartmentChangeHandler.execute_async')
    monkeypatch.setattr(
        ds_module.DepartmentChangeHandler, 'execute_async', dept_execute,
    )

    sync_mock = AsyncMock(name='sync_user')
    monkeypatch.setattr(sync_module.UserTenantSyncService, 'sync_user', sync_mock)

    session_calls = {'add': [], 'commit': 0}

    class _FakeSession:
        async def exec(self, stmt):
            return SimpleNamespace(all=lambda: [], first=lambda: None)

        def add(self, obj):
            session_calls['add'].append(obj)

        async def commit(self):
            session_calls['commit'] += 1

    @asynccontextmanager
    async def _fake_get_session():
        yield _FakeSession()

    monkeypatch.setattr(ds_module, 'get_async_db_session', _fake_get_session)

    return SimpleNamespace(
        dept=dept,
        fake_user=fake_user,
        sync=sync_mock,
        dept_execute=dept_execute,
        session_calls=session_calls,
    )


def test_acreate_local_member_triggers_sync_for_new_user(create_member_patches):
    """A brand-new user must be sync'd to their leaf tenant immediately so
    the tenant user list reflects them without waiting for first login.
    """
    data = SimpleNamespace(
        user_name='alice',
        person_id='BS@alice',
        password='ENCRYPTED',
        role_ids=[99],
    )

    asyncio.run(
        DepartmentService.acreate_local_member('BS@hr', data, _login_user())
    )

    # UserDepartment row inserted as primary.
    inserted = [
        obj for obj in create_member_patches.session_calls['add']
        if hasattr(obj, 'user_id') and hasattr(obj, 'department_id')
    ]
    assert len(inserted) == 1
    assert inserted[0].user_id == 555
    assert inserted[0].is_primary == 1

    # FGA member dispatch fired.
    create_member_patches.dept_execute.assert_awaited_once()

    # sync_user fired with DEPT_CHANGE for the new user.
    create_member_patches.sync.assert_awaited_once()
    args, kwargs = create_member_patches.sync.call_args
    assert args[0] == 555
    assert kwargs.get('trigger') == UserTenantSyncTrigger.DEPT_CHANGE
