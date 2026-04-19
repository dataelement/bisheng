"""Tests for F014 ``LoginSyncService`` orchestration.

Covers the 11-step happy path plus the branch cases:
- T8 core: new user, existing user, primary-dept fallback, parent-chain
  miss, Redis lock contention, disabled user.
- T14: disabled / archived / orphaned leaf tenant → 19303.

Cross-source reuse (T9) and tenant_mapping (T10) live in dedicated files
so each suite has a single orchestration concern.

All downstream collaborators are AsyncMock'd — this keeps the test fast
and makes the ordering contract explicit via ``assert_*_called`` checks.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# =========================================================================
# Helpers
# =========================================================================

def _payload(
    external_user_id='u1', primary='D1', secondary=None,
    ts=1000, name='Alice', email='a@x.com', tenant_mapping=None,
):
    from bisheng.sso_sync.domain.schemas.payloads import (
        LoginSyncRequest, UserAttrsDTO,
    )
    return LoginSyncRequest(
        external_user_id=external_user_id,
        primary_dept_external_id=primary,
        secondary_dept_external_ids=secondary or [],
        user_attrs=UserAttrsDTO(name=name, email=email),
        ts=ts,
        tenant_mapping=tenant_mapping,
    )


def _user(user_id=7, delete=0, source='sso', external_id='u1',
          user_name='Alice', email='a@x.com', phone_number=None):
    return SimpleNamespace(
        user_id=user_id, delete=delete, source=source,
        external_id=external_id, user_name=user_name, email=email,
        phone_number=phone_number,
    )


def _dept(ext, *, id=1, path='/', is_deleted=0, is_tenant_root=0,
          mounted_tenant_id=None):
    return SimpleNamespace(
        id=id, external_id=ext, path=path, is_deleted=is_deleted,
        is_tenant_root=is_tenant_root,
        mounted_tenant_id=mounted_tenant_id,
    )


def _tenant(tid=1, status='active'):
    return SimpleNamespace(id=tid, status=status)


@pytest.fixture()
def patches(monkeypatch):
    """Wire every collaborator LoginSyncService touches. The individual
    tests override the return values as needed."""
    from bisheng.sso_sync.domain.services import login_sync_service as m

    # Redis lock: default acquire=True, release no-op.
    redis_mock = MagicMock()
    redis_mock.asetNx = AsyncMock(return_value=True)
    redis_mock.adelete = AsyncMock(return_value=None)
    monkeypatch.setattr(m, 'get_redis_client', AsyncMock(return_value=redis_mock))

    # Parent chain — default: identity mapping of the primary ext.
    assert_chain = AsyncMock(name='assert_parent_chain_exists')
    monkeypatch.setattr(
        m.DeptUpsertService, 'assert_parent_chain_exists', assert_chain,
    )

    # tenant_mapping — default: noop
    tmh_process = AsyncMock(name='TenantMappingHandler.process')
    monkeypatch.setattr(m.TenantMappingHandler, 'process', tmh_process)

    # User DAO — no existing user by default.
    monkeypatch.setattr(
        m.UserDao, 'aget_by_source_external_id',
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        m.UserDao, 'aget_by_external_id',
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        m.UserDao, 'add_user_and_default_role',
        AsyncMock(side_effect=lambda u: _user(user_id=7, user_name=u.user_name,
                                               email=u.email, source='sso',
                                               external_id=u.external_id)),
    )
    monkeypatch.setattr(
        m.UserDao, 'aupdate_user', AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        m.UserDao, 'aget_token_version', AsyncMock(return_value=0),
    )

    # UserDepartment DAO
    monkeypatch.setattr(
        m.UserDepartmentDao, 'aget_user_primary_department',
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        m.UserDepartmentDao, 'aadd_member', AsyncMock(return_value=None),
    )

    # Internal membership/promote helpers
    monkeypatch.setattr(
        m, '_find_membership', AsyncMock(return_value=None),
    )
    monkeypatch.setattr(m, '_demote_primary', AsyncMock(return_value=None))
    monkeypatch.setattr(m, '_promote_to_primary', AsyncMock(return_value=None))

    # AuditLog for cross-source migration
    monkeypatch.setattr(
        m.AuditLogDao, 'ainsert_v2', AsyncMock(return_value=None),
    )

    # sync_user — returns an active leaf tenant by default.
    sync_user = AsyncMock(return_value=_tenant(tid=15, status='active'))
    monkeypatch.setattr(m.UserTenantSyncService, 'sync_user', sync_user)

    # JWT signer
    monkeypatch.setattr(m, 'AuthJwt', MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(
        m.LoginUser, 'create_access_token',
        MagicMock(return_value='jwt-token-xyz'),
    )

    return SimpleNamespace(
        module=m,
        redis=redis_mock,
        assert_chain=assert_chain,
        tmh_process=tmh_process,
        sync_user=sync_user,
    )


# =========================================================================
# T8 core flow
# =========================================================================

@pytest.mark.asyncio
class TestNewUserHappyPath:

    async def test_returns_user_leaf_tenant_and_token(self, patches):
        from bisheng.sso_sync.domain.services.login_sync_service import (
            LoginSyncService,
        )
        primary = _dept('D1', id=11)
        patches.assert_chain.return_value = {'D1': primary}

        resp = await LoginSyncService.execute(_payload(), request_ip='1.2.3.4')

        assert resp.user_id == 7
        assert resp.leaf_tenant_id == 15
        assert resp.token == 'jwt-token-xyz'

    async def test_sync_user_called_with_login_trigger(self, patches):
        from bisheng.sso_sync.domain.services.login_sync_service import (
            LoginSyncService,
        )
        from bisheng.tenant.domain.constants import UserTenantSyncTrigger
        primary = _dept('D1', id=11)
        patches.assert_chain.return_value = {'D1': primary}

        await LoginSyncService.execute(_payload(), request_ip='1.2.3.4')

        call_args = patches.sync_user.await_args
        # sync_user(user_id, trigger=LOGIN)
        assert call_args.args[0] == 7
        assert call_args.kwargs['trigger'] == UserTenantSyncTrigger.LOGIN


@pytest.mark.asyncio
class TestPrimaryDeptMissingFallback:

    async def test_empty_primary_skips_parent_chain(self, patches):
        from bisheng.sso_sync.domain.services.login_sync_service import (
            LoginSyncService,
        )
        # Root tenant returned by sync_user in the fallback case.
        patches.sync_user.return_value = _tenant(tid=1, status='active')

        payload = _payload(primary=None, secondary=[])
        resp = await LoginSyncService.execute(payload, request_ip='1.2.3.4')

        patches.assert_chain.assert_not_awaited()
        assert resp.leaf_tenant_id == 1


@pytest.mark.asyncio
class TestParentChainMissing:

    async def test_missing_parent_bubbles_19312(self, patches):
        from bisheng.common.errcode.sso_sync import SsoDeptParentMissingError
        from bisheng.sso_sync.domain.services.login_sync_service import (
            LoginSyncService,
        )

        # Simulate DeptUpsertService raising
        patches.assert_chain.side_effect = (
            SsoDeptParentMissingError.http_exception('missing')
        )
        with pytest.raises(Exception) as exc_info:
            await LoginSyncService.execute(_payload(), request_ip='1.2.3.4')
        assert '19312' in str(exc_info.value) or getattr(
            exc_info.value, 'status_code', 0
        ) == SsoDeptParentMissingError.Code


@pytest.mark.asyncio
class TestUserLockBusy:

    async def test_setnx_false_returns_19311(self, patches):
        from bisheng.common.errcode.sso_sync import SsoUserLockBusyError
        from bisheng.sso_sync.domain.services.login_sync_service import (
            LoginSyncService,
        )
        patches.redis.asetNx = AsyncMock(return_value=False)

        with pytest.raises(Exception) as exc_info:
            await LoginSyncService.execute(_payload(), request_ip='1.2.3.4')

        assert getattr(exc_info.value, 'status_code', 0) == \
            SsoUserLockBusyError.Code
        # sync_user must NOT have been called — flow aborted before it.
        patches.sync_user.assert_not_awaited()


@pytest.mark.asyncio
class TestDisabledSsoUser:

    async def test_existing_disabled_user_raises_forbidden(self, patches):
        from bisheng.common.errcode.user import UserForbiddenError
        from bisheng.sso_sync.domain.services.login_sync_service import (
            LoginSyncService,
        )
        m = patches.module
        # Existing same-source user with delete=1
        m.UserDao.aget_by_source_external_id = AsyncMock(
            return_value=_user(user_id=7, delete=1),
        )
        primary = _dept('D1', id=11)
        patches.assert_chain.return_value = {'D1': primary}

        with pytest.raises(Exception) as exc_info:
            await LoginSyncService.execute(_payload(), request_ip='1.2.3.4')
        assert getattr(exc_info.value, 'status_code', 0) == \
            UserForbiddenError.Code


# =========================================================================
# T14 blocked branches
# =========================================================================

@pytest.mark.asyncio
class TestTenantStatusBlocks:

    @pytest.mark.parametrize('status', ['disabled', 'archived', 'orphaned'])
    async def test_non_active_leaf_returns_19303(self, patches, status):
        from bisheng.common.errcode.sso_sync import SsoTenantDisabledError
        from bisheng.sso_sync.domain.services.login_sync_service import (
            LoginSyncService,
        )
        primary = _dept('D1', id=11)
        patches.assert_chain.return_value = {'D1': primary}
        patches.sync_user.return_value = _tenant(tid=15, status=status)

        with pytest.raises(Exception) as exc_info:
            await LoginSyncService.execute(_payload(), request_ip='1.2.3.4')

        assert getattr(exc_info.value, 'status_code', 0) == \
            SsoTenantDisabledError.Code


# =========================================================================
# Existing-user update path (attributes dirty)
# =========================================================================

@pytest.mark.asyncio
class TestExistingUserAttrUpdate:

    async def test_name_change_triggers_update(self, patches):
        from bisheng.sso_sync.domain.services.login_sync_service import (
            LoginSyncService,
        )
        m = patches.module
        existing = _user(user_id=7, user_name='OldName', email='old@x.com',
                         source='sso', external_id='u1')
        m.UserDao.aget_by_source_external_id = AsyncMock(return_value=existing)
        primary = _dept('D1', id=11)
        patches.assert_chain.return_value = {'D1': primary}

        await LoginSyncService.execute(_payload(name='NewName', email='new@x.com'),
                                       request_ip='1.2.3.4')

        m.UserDao.aupdate_user.assert_awaited_once()
        updated_user = m.UserDao.aupdate_user.await_args.args[0]
        assert updated_user.user_name == 'NewName'
        assert updated_user.email == 'new@x.com'
