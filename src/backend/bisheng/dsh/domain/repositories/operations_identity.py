"""Fresh existing identity records for privileged DSH operational commands."""

from bisheng.core.context.tenant import bypass_tenant_filter


class OperationsIdentityRecords:
    async def actor(self, user_id: int) -> dict | None:
        from bisheng.database.models.tenant import TenantDao, UserTenantDao
        from bisheng.user.domain.models.user import UserDao

        with bypass_tenant_filter():
            user = await UserDao.aget_user(user_id)
            membership = await UserTenantDao.aget_active_user_tenant(user_id)
            tenant = await TenantDao.aget_by_id(membership.tenant_id) if membership else None
        if user is None:
            return None
        return {
            "user_id": user.user_id,
            "user_name": user.user_name,
            "active": user.delete == 0 and membership is not None and tenant is not None and tenant.status == "active",
            "token_version": user.token_version,
            "tenant_id": membership.tenant_id if membership else None,
        }

    async def active_tenant(self, tenant_id: int) -> bool:
        from bisheng.database.models.tenant import TenantDao

        with bypass_tenant_filter():
            tenant = await TenantDao.aget_by_id(tenant_id)
        return tenant is not None and tenant.status == "active"

    async def active_tenant_ids(self) -> list[int]:
        from bisheng.database.models.tenant import TenantDao

        result = []
        page = 1
        while True:
            rows, total = await TenantDao.alist_tenants(status="active", page=page, page_size=100)
            result.extend(row.id for row in rows)
            if page * 100 >= total or not rows:
                return result
            page += 1
