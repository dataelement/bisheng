from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.tenant.domain.repositories.implementations.tenant_membership_repository_impl import (
    TenantMembershipRepositoryImpl,
)


async def test_repository_keeps_disabled_current_and_missing_tenant(async_db_session):
    """AC-05, AC-06: 当前关系不因状态、历史或缺失租户被静默过滤。"""
    db = async_db_session
    db.add(Tenant(id=80, tenant_code="e2e-mcp-80", tenant_name="e2e-mcp-tenant", status="disabled"))
    db.add_all(
        [
            UserTenant(user_id=80, tenant_id=999, is_active=1, status="disabled"),
            UserTenant(user_id=80, tenant_id=80, is_active=None, is_default=1, status="active"),
            UserTenant(user_id=81, tenant_id=80, is_active=1, status="active"),
        ]
    )
    await db.commit()
    repo = TenantMembershipRepositoryImpl(db)
    rows = await repo.list_current_by_user(80)
    assert len(rows) == 1 and rows[0].tenant_id == 999 and rows[0].status == "disabled"
    assert await repo.find_tenant(999) is None
    assert (await repo.find_tenant(80)).status == "disabled"
    assert await repo.list_current_by_user(82) == []
