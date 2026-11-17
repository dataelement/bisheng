"""Mount preserves original effective grants while execution identity follows Home."""

from unittest.mock import AsyncMock

import pytest
from sqlmodel import delete, select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.audit_log import AuditLog
from bisheng.database.models.department import Department
from bisheng.database.models.role import Role
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.database.models.user_role import UserRole
from bisheng.role.application.effective_roles import load_effective_roles
from bisheng.tenant.domain.constants import UserTenantSyncTrigger
from bisheng.tenant.domain.services.tenant_resolver import TenantResolver
from bisheng.tenant.domain.services.user_tenant_sync_service import UserTenantSyncService
from bisheng.user.domain.services.user import UserService
from test.fixtures.managed_tenant import managed_db as managed_db
from test.role.test_effective_roles import policy_db as policy_db


@pytest.fixture
async def mount_db(policy_db, monkeypatch):
    from bisheng.admin.domain.services.tenant_scope import TenantScopeService
    from bisheng.database.models import tenant
    from bisheng.user.domain.models import user

    await policy_db.create(AuditLog)
    monkeypatch.setattr(tenant, "get_async_db_session", policy_db.sessions)
    monkeypatch.setattr(user, "get_async_db_session", policy_db.sessions)
    monkeypatch.setattr(UserService, "_dsh_enabled", lambda: False)
    monkeypatch.setattr(UserTenantSyncService, "_count_owned_resources", AsyncMock(return_value=0))
    for name in (
        "_rewrite_tenant_membership_permissions",
        "_invalidate_redis_caches",
        "_migrate_relocated_personal_token",
        "_write_relocation_audit",
    ):
        monkeypatch.setattr(UserTenantSyncService, name, AsyncMock())
    monkeypatch.setattr(TenantScopeService, "clear_on_token_version_bump", AsyncMock())
    with bypass_tenant_filter():
        async with policy_db.sessions() as session:
            await session.exec(delete(UserRole).where(UserRole.user_id == 77))
            session.add(Role(id=9, role_name="Root private", role_type="tenant", tenant_id=1))
            session.add(Role(id=10, role_name="new department default", role_type="tenant", tenant_id=2))
            session.add_all(
                [
                    UserRole(id=20, user_id=77, role_id=2, tenant_id=1),
                    UserRole(id=21, user_id=77, role_id=9, tenant_id=1),
                ]
            )
            (await session.get(UserTenant, 1)).tenant_id = 1
            (await session.get(Department, 30)).default_role_ids = [2, 10]
            await session.commit()
            home = await session.get(Tenant, 2)
    monkeypatch.setattr(TenantResolver, "resolve_user_leaf_tenant", AsyncMock(return_value=home))
    return policy_db


async def binding_snapshot(database):
    with bypass_tenant_filter():
        async with database.sessions() as session:
            rows = (await session.exec(select(UserRole).where(UserRole.user_id == 77).order_by(UserRole.id))).all()
            return [row.model_dump() for row in rows]


@pytest.mark.parametrize("has_active_home", [True, False])
@pytest.mark.parametrize(
    "trigger",
    [
        UserTenantSyncTrigger.MOUNT_BACKFILL,
        UserTenantSyncTrigger.LOGIN,
        UserTenantSyncTrigger.CELERY_RECONCILE,
        UserTenantSyncTrigger.MANUAL,
    ],
)
async def test_mount_and_deferred_sync_preserve_all_binding_fields(mount_db, has_active_home, trigger):
    if not has_active_home:
        with bypass_tenant_filter():
            async with mount_db.sessions() as session:
                (await session.get(UserTenant, 1)).is_active = None
                await session.commit()
    before = await binding_snapshot(mount_db)
    assert (await UserTenantSyncService.sync_user(77, trigger=trigger)).id == 2
    assert await binding_snapshot(mount_db) == before
    policy = await load_effective_roles(77)
    assert policy.home_tenant_id == 2 and policy.role_ids == (2, 9)
    assert policy.web_menu == frozenset({"tool", "wrong-owner"})
    await UserTenantSyncService.sync_user(77, trigger=UserTenantSyncTrigger.LOGIN)
    assert await binding_snapshot(mount_db) == before


async def test_mount_does_not_give_defaults_to_previously_unassigned_person(mount_db):
    with bypass_tenant_filter():
        async with mount_db.sessions() as session:
            await session.exec(delete(UserRole).where(UserRole.user_id == 77))
            await session.commit()
    await UserTenantSyncService.sync_user(77, trigger=UserTenantSyncTrigger.MOUNT_BACKFILL)
    assert await binding_snapshot(mount_db) == []


async def test_actual_department_change_keeps_existing_retirement_and_default_policy(mount_db):
    await UserTenantSyncService.sync_user(77, trigger=UserTenantSyncTrigger.DEPT_CHANGE)
    assert {(row["role_id"], row["tenant_id"]) for row in await binding_snapshot(mount_db)} == {(2, 2), (10, 2)}
