"""Tests for F014 source-preserving cross-source user reuse branch (T9).

PRD §9.2.6 + Phase-3 decision 2: when an SSO payload's external_user_id
already exists under a *different* source (e.g., manually imported
``source='local'`` users), reuse the record and preserve its original
``source`` instead of creating a duplicate account.

All downstream DAOs/services are mocked; we only care about the decision
tree inside :meth:`LoginSyncService._upsert_user`.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def _payload(external_user_id="u1", name="Alice", email="alice@x.com", phone=None):
    from bisheng.sso_sync.domain.schemas.payloads import (
        LoginSyncRequest,
        UserAttrsDTO,
    )

    return LoginSyncRequest(
        external_user_id=external_user_id,
        primary_dept_external_id="D1",
        secondary_dept_external_ids=[],
        user_attrs=UserAttrsDTO(name=name, email=email, phone=phone),
        ts=1000,
    )


def _user(user_id=7, delete=0, source="local", external_id="u1", user_name="Alice", email="a@x.com", phone_number=None):
    return SimpleNamespace(
        user_id=user_id,
        delete=delete,
        source=source,
        external_id=external_id,
        user_name=user_name,
        email=email,
        phone_number=phone_number,
    )


def _dept(ext, *, id=1, path="/", is_deleted=0):
    return SimpleNamespace(
        id=id,
        external_id=ext,
        path=path,
        is_deleted=is_deleted,
        is_tenant_root=0,
        mounted_tenant_id=None,
    )


def _tenant(tid=15, status="active"):
    return SimpleNamespace(id=tid, status=status)


@pytest.fixture()
def patches(monkeypatch):
    from bisheng.sso_sync.domain.services import login_sync_service as m

    redis = MagicMock()
    redis.async_connection = MagicMock()
    redis.async_connection.set = AsyncMock(return_value=True)
    redis.adelete = AsyncMock()
    monkeypatch.setattr(m, "get_redis_client", AsyncMock(return_value=redis))

    monkeypatch.setattr(
        m.DeptUpsertService,
        "assert_parent_chain_exists",
        AsyncMock(return_value={"D1": _dept("D1", id=11)}),
    )
    monkeypatch.setattr(
        m.TenantMappingHandler,
        "process",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        m.UserDepartmentDao,
        "aget_user_primary_department",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        m.UserDepartmentDao,
        "aadd_member",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        m.UserDepartmentDao,
        "aget_membership",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        m.UserDepartmentDao,
        "aset_primary_flag",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        m.UserDepartmentDao,
        "aget_memberships_in_depts",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        m.UserDepartmentDao,
        "aget_user_departments",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        m.DepartmentChangeHandler,
        "execute_async",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        m.UserTenantSyncService,
        "sync_user",
        AsyncMock(return_value=_tenant()),
    )
    monkeypatch.setattr(
        m.UserService,
        "_reject_login_if_user_has_no_usable_access",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        m.UserDao,
        "aget_token_version",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        m.LegacyRBACSyncService,
        "sync_user_auth_created",
        AsyncMock(return_value=None),
    )
    from bisheng.database.models.tenant import UserTenantDao

    monkeypatch.setattr(
        UserTenantDao,
        "aactivate_user_tenant",
        AsyncMock(return_value=SimpleNamespace(tenant_id=1)),
    )
    monkeypatch.setattr(m, "AuthJwt", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(
        m.LoginUser,
        "create_access_token",
        MagicMock(return_value="jwt-token"),
    )

    return m


# =========================================================================
# Cases
# =========================================================================


@pytest.mark.asyncio
class TestCrossSourceReusePreservesSource:
    async def test_feishu_user_reused_and_source_preserved(self, patches):
        """Existing source='feishu' user → reuse without changing source."""
        from bisheng.sso_sync.domain.services.login_sync_service import (
            LoginSyncService,
        )

        feishu_user = _user(user_id=7, source="feishu", external_id="u1", user_name="Alice", email="alice@x.com")
        aget_src = AsyncMock(return_value=None)
        aget_any = AsyncMock(return_value=feishu_user)
        update = AsyncMock(return_value=None)
        add = AsyncMock(return_value=None)
        patches.UserDao.aget_by_source_external_id = aget_src
        patches.UserDao.aget_by_external_id = aget_any
        patches.UserDao.aupdate_user = update
        patches.UserDao.add_user_and_default_role = add

        resp = await LoginSyncService.execute(
            _payload(),
            request_ip="1.2.3.4",
            row_source="sso",
        )

        # Result: reused the feishu user's id.
        assert resp.user_id == 7
        assert feishu_user.source == "feishu"
        update.assert_awaited()
        add.assert_not_awaited()  # no new user created

    async def test_cross_source_reuse_syncs_user_attrs(self, patches):
        from bisheng.sso_sync.domain.services.login_sync_service import (
            LoginSyncService,
        )

        local_user = _user(
            user_id=7, source="local", external_id="u1", user_name="u1", email="old@x.com", phone_number=None
        )
        patches.UserDao.aget_by_source_external_id = AsyncMock(return_value=None)
        patches.UserDao.aget_by_external_id = AsyncMock(return_value=local_user)
        update = AsyncMock(return_value=None)
        patches.UserDao.aupdate_user = update
        patches.UserDao.add_user_and_default_role = AsyncMock()

        await LoginSyncService.execute(
            _payload(name="Alice", email="alice@x.com", phone="13800000000"),
            request_ip="1.2.3.4",
            row_source="sso",
        )

        update.assert_awaited_once()
        updated_user = update.await_args.args[0]
        assert updated_user.source == "local"
        assert updated_user.user_name == "Alice"
        assert updated_user.email == "alice@x.com"
        assert updated_user.phone_number == "13800000000"
        assert updated_user.update_time is not None

    async def test_missing_sso_user_rejected_without_creation(self, patches):
        from bisheng.common.errcode.sso_sync import SsoUserNotFoundError
        from bisheng.sso_sync.domain.services.login_sync_service import (
            LoginSyncService,
        )

        patches.UserDao.aget_by_source_external_id = AsyncMock(return_value=None)
        patches.UserDao.aget_by_external_id = AsyncMock(return_value=None)
        add = AsyncMock()
        patches.UserDao.add_user_and_default_role = add

        with pytest.raises(Exception) as exc_info:
            await LoginSyncService.execute(
                _payload(external_user_id="u2", name="Bob", email="bob@x.com"),
                request_ip="1.2.3.4",
                row_source="sso",
            )

        assert getattr(exc_info.value, "status_code", 0) == SsoUserNotFoundError.Code
        add.assert_not_awaited()

    async def test_cross_source_deleted_account_raises_forbidden(self, patches):
        """If the legacy cross-source account is already disabled (delete=1),
        refuse to adopt it silently."""
        from bisheng.common.errcode.user import UserForbiddenError
        from bisheng.sso_sync.domain.services.login_sync_service import (
            LoginSyncService,
        )

        disabled = _user(user_id=7, source="feishu", delete=1)
        patches.UserDao.aget_by_source_external_id = AsyncMock(return_value=None)
        patches.UserDao.aget_by_external_id = AsyncMock(return_value=disabled)
        patches.UserDao.aupdate_user = AsyncMock()
        patches.UserDao.add_user_and_default_role = AsyncMock()

        with pytest.raises(Exception) as exc_info:
            await LoginSyncService.execute(
                _payload(),
                request_ip="1.2.3.4",
                row_source="sso",
            )
        assert getattr(exc_info.value, "status_code", 0) == UserForbiddenError.Code
        patches.UserDao.add_user_and_default_role.assert_not_awaited()

    async def test_same_source_race_reused_no_migration(self, patches):
        """Rare race: another writer has already created the same source row."""
        from bisheng.sso_sync.domain.services.login_sync_service import (
            LoginSyncService,
        )

        raced = _user(user_id=7, source="sso", external_id="u1")
        patches.UserDao.aget_by_source_external_id = AsyncMock(return_value=None)
        patches.UserDao.aget_by_external_id = AsyncMock(return_value=raced)
        patches.UserDao.aupdate_user = AsyncMock()
        patches.UserDao.add_user_and_default_role = AsyncMock()

        resp = await LoginSyncService.execute(
            _payload(),
            request_ip="1.2.3.4",
            row_source="sso",
        )

        assert resp.user_id == 7
        patches.UserDao.add_user_and_default_role.assert_not_awaited()
