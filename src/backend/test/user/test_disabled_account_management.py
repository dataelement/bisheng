"""Account recovery proves ownership without granting disabled users a policy."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from starlette.requests import Request

from bisheng.common.errcode.role import RolePermissionDeniedError, RolePolicyUnavailableError
from bisheng.common.request_scope import admitted_request_scope
from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope
from bisheng.database.models.user_role import UserRole
from bisheng.role.application.effective_roles import load_effective_roles
from bisheng.user.application.management_subject import require_management_subject
from bisheng.user.domain.models.user import User, UserUpdate
from test.fixtures.managed_tenant import managed_db as managed_db
from test.role.test_effective_roles import policy_db as policy_db


async def test_disabled_member_can_be_reenabled_but_has_no_effective_roles(policy_db, monkeypatch):
    from sqlmodel import delete

    from bisheng.user.api import user as api

    with bypass_tenant_filter():
        async with policy_db.sessions() as session:
            member = await session.get(User, 77)
            member.delete = 1
            await session.exec(delete(UserRole).where(UserRole.user_id == 77, UserRole.role_id == 1))
            await session.commit()
    monkeypatch.setattr(api, "get_sync_db_session", policy_db.sync_sessions)
    monkeypatch.setattr(api.UserDao, "get_user", Mock(return_value=member))
    monkeypatch.setattr(api.UserService, "persist_profile_update", lambda user: user)
    monkeypatch.setattr(api, "clear_error_password_key", Mock())
    monkeypatch.setattr(api, "update_user_delete_hook", Mock())
    token = admitted_request_scope.set(SimpleNamespace(kind="tenant", tenant_id=2))
    try:
        with tenant_execution_scope(2):
            await require_management_subject(77)
            with pytest.raises(RolePolicyUnavailableError):
                await load_effective_roles(77)
            result = await api.update(
                request=Request({"type": "http", "headers": []}),
                user=UserUpdate(user_id=77, delete=0),
                login_user=SimpleNamespace(is_admin=lambda: True),
            )
            assert result.status_code == 200
            assert member.delete == 0
    finally:
        admitted_request_scope.reset(token)


async def test_disabled_foreign_member_still_cannot_be_managed(policy_db):
    with bypass_tenant_filter():
        async with policy_db.sessions() as session:
            (await session.get(User, 77)).delete = 1
            await session.commit()
    token = admitted_request_scope.set(SimpleNamespace(kind="tenant", tenant_id=3))
    try:
        with pytest.raises(RolePermissionDeniedError):
            await require_management_subject(77)
    finally:
        admitted_request_scope.reset(token)
