"""Tests for F014 cross-source user reuse branch (T9).

PRD §9.2.6 + Phase-3 decision 2: when an SSO payload's external_user_id
already exists under a *different* source (e.g., feishu via F009 org-sync),
reuse the record and migrate ``source='sso'`` instead of creating a
duplicate account. Writes an ``action='user.source_migrated'`` audit row.

All downstream DAOs/services are mocked; we only care about the decision
tree inside :meth:`LoginSyncService._upsert_user`.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def _payload(external_user_id='u1', name='Alice', email='alice@x.com'):
    from bisheng.sso_sync.domain.schemas.payloads import (
        LoginSyncRequest, UserAttrsDTO,
    )
    return LoginSyncRequest(
        external_user_id=external_user_id,
        primary_dept_external_id='D1',
        secondary_dept_external_ids=[],
        user_attrs=UserAttrsDTO(name=name, email=email),
        ts=1000,
    )


def _user(user_id=7, delete=0, source='local', external_id='u1',
          user_name='Alice', email='a@x.com', phone_number=None):
    return SimpleNamespace(
        user_id=user_id, delete=delete, source=source,
        external_id=external_id, user_name=user_name, email=email,
        phone_number=phone_number,
    )


def _dept(ext, *, id=1, path='/', is_deleted=0):
    return SimpleNamespace(
        id=id, external_id=ext, path=path, is_deleted=is_deleted,
        is_tenant_root=0, mounted_tenant_id=None,
    )


def _tenant(tid=15, status='active'):
    return SimpleNamespace(id=tid, status=status)


@pytest.fixture()
def patches(monkeypatch):
    from bisheng.sso_sync.domain.services import login_sync_service as m

    redis = MagicMock()
    redis.async_connection = MagicMock()
    redis.async_connection.set = AsyncMock(return_value=True)
    redis.adelete = AsyncMock()
    monkeypatch.setattr(m, 'get_redis_client', AsyncMock(return_value=redis))

    monkeypatch.setattr(
        m.DeptUpsertService, 'assert_parent_chain_exists',
        AsyncMock(return_value={'D1': _dept('D1', id=11)}),
    )
    monkeypatch.setattr(
        m.TenantMappingHandler, 'process', AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        m.UserDepartmentDao, 'aget_user_primary_department',
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        m.UserDepartmentDao, 'aadd_member', AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        m.UserDepartmentDao, 'aget_membership', AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        m.UserDepartmentDao, 'aset_primary_flag', AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        m.UserDepartmentDao, 'aget_memberships_in_depts',
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        m.UserTenantSyncService, 'sync_user', AsyncMock(return_value=_tenant()),
    )
    monkeypatch.setattr(
        m.UserDao, 'aget_token_version', AsyncMock(return_value=0),
    )
    monkeypatch.setattr(m, 'AuthJwt', MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(
        m.LoginUser, 'create_access_token',
        MagicMock(return_value='jwt-token'),
    )

    return m


# =========================================================================
# Cases
# =========================================================================

@pytest.mark.asyncio
class TestCrossSourceReuseAndMigrate:

    async def test_feishu_user_reused_and_source_migrated(self, patches):
        """Existing source='feishu' user → reuse + UPDATE source='sso'
        + audit ``user.source_migrated``."""
        from bisheng.sso_sync.domain.services.login_sync_service import (
            LoginSyncService,
        )
        feishu_user = _user(user_id=7, source='feishu', external_id='u1',
                            user_name='Alice', email='alice@x.com')
        aget_src = AsyncMock(return_value=None)
        aget_any = AsyncMock(return_value=feishu_user)
        update = AsyncMock(return_value=None)
        audit = AsyncMock(return_value=None)
        add = AsyncMock(return_value=None)
        patches.UserDao.aget_by_source_external_id = aget_src
        patches.UserDao.aget_by_external_id = aget_any
        patches.UserDao.aupdate_user = update
        patches.UserDao.add_user_and_default_role = add
        patches.AuditLogDao.ainsert_v2 = audit

        resp = await LoginSyncService.execute(_payload(), request_ip='1.2.3.4')

        # Result: reused the feishu user's id.
        assert resp.user_id == 7
        # source mutated on the user object before update
        assert feishu_user.source == 'sso'
        update.assert_awaited()
        add.assert_not_awaited()  # no new user created
        # Audit written
        audit.assert_awaited()
        action = audit.await_args.kwargs.get('action')
        metadata = audit.await_args.kwargs.get('metadata') or {}
        assert action == 'user.source_migrated'
        assert metadata.get('old_source') == 'feishu'
        assert metadata.get('new_source') == 'sso'

    async def test_new_sso_user_created_when_truly_missing(self, patches):
        from bisheng.sso_sync.domain.services.login_sync_service import (
            LoginSyncService,
        )
        created = _user(user_id=11, source='sso', external_id='u2',
                        user_name='Bob', email='bob@x.com')
        patches.UserDao.aget_by_source_external_id = AsyncMock(return_value=None)
        patches.UserDao.aget_by_external_id = AsyncMock(return_value=None)
        add = AsyncMock(return_value=created)
        patches.UserDao.add_user_and_default_role = add
        audit = AsyncMock()
        patches.AuditLogDao.ainsert_v2 = audit

        resp = await LoginSyncService.execute(
            _payload(external_user_id='u2', name='Bob', email='bob@x.com'),
            request_ip='1.2.3.4',
        )

        add.assert_awaited_once()
        assert resp.user_id == 11
        # No migration audit (nothing migrated)
        audit.assert_not_awaited()

    async def test_cross_source_deleted_account_raises_forbidden(self, patches):
        """If the legacy cross-source account is already disabled (delete=1),
        refuse to adopt it silently."""
        from bisheng.common.errcode.user import UserForbiddenError
        from bisheng.sso_sync.domain.services.login_sync_service import (
            LoginSyncService,
        )
        disabled = _user(user_id=7, source='feishu', delete=1)
        patches.UserDao.aget_by_source_external_id = AsyncMock(return_value=None)
        patches.UserDao.aget_by_external_id = AsyncMock(return_value=disabled)
        patches.UserDao.aupdate_user = AsyncMock()
        patches.UserDao.add_user_and_default_role = AsyncMock()

        with pytest.raises(Exception) as exc_info:
            await LoginSyncService.execute(_payload(), request_ip='1.2.3.4')
        assert getattr(exc_info.value, 'status_code', 0) == \
            UserForbiddenError.Code
        patches.UserDao.add_user_and_default_role.assert_not_awaited()

    async def test_same_source_race_reused_no_migration(self, patches):
        """Rare race: another writer has already flipped the row to
        source='sso' between our two DAO lookups. Adopt the row, but do
        NOT write a migration audit (nothing to migrate)."""
        from bisheng.sso_sync.domain.services.login_sync_service import (
            LoginSyncService,
        )
        raced = _user(user_id=7, source='sso', external_id='u1')
        patches.UserDao.aget_by_source_external_id = AsyncMock(return_value=None)
        patches.UserDao.aget_by_external_id = AsyncMock(return_value=raced)
        patches.UserDao.aupdate_user = AsyncMock()
        patches.UserDao.add_user_and_default_role = AsyncMock()
        audit = AsyncMock()
        patches.AuditLogDao.ainsert_v2 = audit

        resp = await LoginSyncService.execute(_payload(), request_ip='1.2.3.4')

        assert resp.user_id == 7
        audit.assert_not_awaited()
        patches.UserDao.add_user_and_default_role.assert_not_awaited()
