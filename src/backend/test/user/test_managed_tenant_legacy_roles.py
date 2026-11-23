"""Legacy API role reset uses target H and rejects foreign affiliation grants."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlmodel import delete, select

from bisheng.common.errcode.role import RolePermissionDeniedError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.user_role import UserRole
from bisheng.user.domain.models.user_role import UserRoleCreate
from test.fixtures.managed_tenant import managed_db as managed_db
from test.fixtures.managed_tenant import management_scope
from test.role.test_effective_roles import policy_db as policy_db
from test.user.test_managed_tenant_bindings import binding_db as binding_db


async def test_legacy_reset_writes_target_home_under_foreign_management_view(binding_db, monkeypatch):
    from bisheng.user.api import user as endpoint

    with bypass_tenant_filter():
        async with binding_db.sessions() as session:
            await session.exec(delete(UserRole).where(UserRole.user_id == 77, UserRole.role_id == 1))
            await session.commit()
    monkeypatch.setattr(endpoint, "update_user_role_hook", Mock())
    monkeypatch.setattr(endpoint.LegacyRBACSyncService, "sync_user_role_change", AsyncMock())
    with management_scope(1, 3):
        result = await endpoint.user_addrole(
            request=None,
            user_role=UserRoleCreate(user_id=77, role_id=[2, 3]),
            login_user=SimpleNamespace(user_id=7, tenant_id=1, is_admin=lambda: True),
        )
    assert result.status_code == 200
    with bypass_tenant_filter():
        async with binding_db.sessions() as session:
            home_roles = {
                row.role_id
                for row in (
                    await session.exec(select(UserRole).where(UserRole.user_id == 77, UserRole.tenant_id == 2))
                ).all()
            }
            assert home_roles == {2, 3}
            assert (await session.exec(select(UserRole).where(UserRole.user_id == 77, UserRole.tenant_id == 3))).all()


async def test_nonadmin_legacy_reset_cannot_use_foreign_affiliation(binding_db):
    from bisheng.user.api import user as endpoint

    with bypass_tenant_filter():
        async with binding_db.sessions() as session:
            await session.exec(delete(UserRole).where(UserRole.user_id == 77, UserRole.role_id == 1))
            await session.commit()
    with management_scope(3, 3), pytest.raises(RolePermissionDeniedError):
        await endpoint.user_addrole(
            request=None,
            user_role=UserRoleCreate(user_id=77, role_id=[2]),
            login_user=SimpleNamespace(user_id=7, tenant_id=3, is_admin=lambda: False),
        )


async def test_legacy_create_rejects_foreign_role_before_user_insert(binding_db, monkeypatch):
    from bisheng.api.v1.schemas import CreateUserReq, GroupAndRoles
    from bisheng.user.domain.models.user import UserDao
    from bisheng.user.domain.services.user import UserService

    monkeypatch.setattr(UserService, "decrypt_md5_password_strict", Mock(return_value="fixture-hash"))
    insert = Mock(side_effect=AssertionError("User inserted before role qualification"))
    monkeypatch.setattr(UserDao, "add_user_with_groups_and_roles", insert)
    req = CreateUserReq(
        user_name="new-account", password="fixture-only", group_roles=[GroupAndRoles(group_id=1, role_ids=[4])]
    )
    with management_scope(1, 3), pytest.raises(RolePermissionDeniedError):
        await UserService.create_user(None, SimpleNamespace(user_id=7, is_admin=lambda: True), req)
    insert.assert_not_called()
