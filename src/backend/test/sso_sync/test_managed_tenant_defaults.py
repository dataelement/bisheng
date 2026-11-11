"""Default seeds are limited to actual new same-home memberships."""

from sqlmodel import delete, select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.audit_log import AuditLog
from bisheng.database.models.department import Department
from bisheng.database.models.user_role import UserRole
from bisheng.user.application.policy_bindings import seed_policy_defaults
from test.fixtures.managed_tenant import managed_db as managed_db
from test.role.test_effective_roles import policy_db as policy_db


async def test_snapshot_replay_does_not_restore_revoked_default(policy_db):
    await policy_db.create(AuditLog)
    with bypass_tenant_filter():
        async with policy_db.sessions() as session:
            dept = await session.get(Department, 30)
            dept.default_role_ids = [2, 3]
            await session.exec(delete(UserRole).where(UserRole.user_id == 77, UserRole.role_id == 3))
            await session.commit()
    await seed_policy_defaults(77, set())
    with bypass_tenant_filter():
        async with policy_db.sessions() as session:
            assert not (await session.exec(select(UserRole).where(UserRole.user_id == 77, UserRole.role_id == 3))).all()
    await seed_policy_defaults(77, {30})
    with bypass_tenant_filter():
        async with policy_db.sessions() as session:
            assert {
                row.tenant_id
                for row in (
                    await session.exec(select(UserRole).where(UserRole.user_id == 77, UserRole.role_id == 3))
                ).all()
            } == {2}


async def test_foreign_secondary_does_not_seed_even_global_role(policy_db):
    await policy_db.create(AuditLog)
    with bypass_tenant_filter():
        async with policy_db.sessions() as session:
            dept = await session.get(Department, 40)
            dept.default_role_ids = [2, 4, 5]
            await session.exec(delete(UserRole).where(UserRole.user_id == 77, UserRole.role_id == 2))
            await session.commit()
    await seed_policy_defaults(77, {40})
    with bypass_tenant_filter():
        async with policy_db.sessions() as session:
            assert not (await session.exec(select(UserRole).where(UserRole.user_id == 77, UserRole.role_id == 2))).all()


async def test_first_sso_activation_rebinds_explicit_account_default_but_replay_does_not(policy_db, monkeypatch):
    from unittest.mock import AsyncMock

    import bisheng.database.models.tenant as tenants
    import bisheng.user.domain.models.user as users
    from bisheng.database.models.department import UserDepartment
    from bisheng.database.models.tenant import Tenant
    from bisheng.tenant.domain.services.tenant_resolver import TenantResolver
    from bisheng.tenant.domain.services.user_tenant_sync_service import UserTenantSyncService
    from bisheng.user.domain.models.user import User
    from bisheng.user.domain.services.user import UserService

    await policy_db.create(AuditLog)
    monkeypatch.setattr(tenants, "get_async_db_session", policy_db.sessions)
    monkeypatch.setattr(users, "get_async_db_session", policy_db.sessions)
    monkeypatch.setattr(UserService, "_dsh_enabled", lambda: False)
    with bypass_tenant_filter():
        async with policy_db.sessions() as session:
            session.add(User(user_id=79, user_name="sso-new", password="fixture-only"))
            session.add(UserDepartment(id=21, user_id=79, department_id=30, is_primary=1))
            session.add(UserRole(id=21, user_id=79, role_id=2, tenant_id=1))
            await session.commit()
            home = await session.get(Tenant, 2)
    monkeypatch.setattr(TenantResolver, "resolve_user_leaf_tenant", AsyncMock(return_value=home))
    for name in (
        "_rewrite_tenant_membership_permissions",
        "_invalidate_redis_caches",
        "_migrate_relocated_personal_token",
        "_write_relocation_audit",
    ):
        monkeypatch.setattr(UserTenantSyncService, name, AsyncMock())
    await UserTenantSyncService.sync_user(79)
    with bypass_tenant_filter():
        async with policy_db.sessions() as session:
            bindings = (await session.exec(select(UserRole).where(UserRole.user_id == 79))).all()
            assert [(row.role_id, row.tenant_id) for row in bindings] == [(2, 2)]
            await session.delete(bindings[0])
            await session.commit()
    await UserTenantSyncService.sync_user(79)
    with bypass_tenant_filter():
        async with policy_db.sessions() as session:
            assert not (await session.exec(select(UserRole).where(UserRole.user_id == 79))).all()


async def test_disabled_mount_does_not_relocate_or_delete_bindings_on_login(policy_db, monkeypatch):
    from unittest.mock import AsyncMock

    import pytest

    from bisheng.common.errcode.role import RolePolicyUnavailableError
    from bisheng.database.models.tenant import Tenant, UserTenantDao
    from bisheng.tenant.domain.services.tenant_resolver import TenantResolver
    from bisheng.tenant.domain.services.user_tenant_sync_service import UserTenantSyncService

    with bypass_tenant_filter():
        async with policy_db.sessions() as session:
            tenant = await session.get(Tenant, 2)
            tenant.status = "disabled"
            root = await session.get(Tenant, 1)
            await session.commit()
    monkeypatch.setattr(TenantResolver, "resolve_user_leaf_tenant", AsyncMock(return_value=root))
    activate = AsyncMock()
    monkeypatch.setattr(UserTenantDao, "aactivate_user_tenant", activate)
    with pytest.raises(RolePolicyUnavailableError):
        await UserTenantSyncService.sync_user(77)
    activate.assert_not_awaited()
    with bypass_tenant_filter():
        async with policy_db.sessions() as session:
            assert len((await session.exec(select(UserRole).where(UserRole.user_id == 77))).all()) == 7


async def test_relocation_and_return_never_revive_historical_home_grants(policy_db, monkeypatch):
    from unittest.mock import AsyncMock

    import bisheng.database.models.tenant as tenants
    import bisheng.user.domain.models.user as users
    from bisheng.database.models.department import UserDepartment
    from bisheng.database.models.tenant import Tenant
    from bisheng.tenant.domain.services.tenant_resolver import TenantResolver
    from bisheng.tenant.domain.services.user_tenant_sync_service import UserTenantSyncService
    from bisheng.user.domain.services.user import UserService

    await policy_db.create(AuditLog)
    monkeypatch.setattr(tenants, "get_async_db_session", policy_db.sessions)
    monkeypatch.setattr(users, "get_async_db_session", policy_db.sessions)
    monkeypatch.setattr(UserService, "_dsh_enabled", lambda: False)
    for name in (
        "_rewrite_tenant_membership_permissions",
        "_invalidate_redis_caches",
        "_migrate_relocated_personal_token",
        "_write_relocation_audit",
    ):
        monkeypatch.setattr(UserTenantSyncService, name, AsyncMock())
    monkeypatch.setattr(UserTenantSyncService, "_count_owned_resources", AsyncMock(return_value=0))
    for primary_id, home_id in [(40, 3), (30, 2)]:
        with bypass_tenant_filter():
            async with policy_db.sessions() as session:
                (await session.get(UserDepartment, 1)).is_primary = int(primary_id == 30)
                (await session.get(UserDepartment, 2)).is_primary = int(primary_id == 40)
                home = await session.get(Tenant, home_id)
                await session.commit()
        monkeypatch.setattr(TenantResolver, "resolve_user_leaf_tenant", AsyncMock(return_value=home))
        await UserTenantSyncService.sync_user(77)
        with bypass_tenant_filter():
            async with policy_db.sessions() as session:
                bindings = (await session.exec(select(UserRole).where(UserRole.user_id == 77))).all()
                assert [(row.role_id, row.tenant_id) for row in bindings] == [(1, 1)]
