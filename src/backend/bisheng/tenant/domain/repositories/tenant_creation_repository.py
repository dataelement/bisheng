"""Tenant, root Department and memberships in the caller-owned transaction."""

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.tenant import TenantCreationFailedError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.department import Department
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.resource_reference.application.contracts import TransactionIdentity


class TenantCreationRepository:
    async def acreate(self, session, *, tenant, department_id, admin_user_ids):
        if (
            not isinstance(session, AsyncSession)
            or type(tenant) is not Tenant
            or tenant.id is not None
            or session.new
            or session.dirty
            or session.deleted
            or not session.in_transaction()
            or type(admin_user_ids) is not tuple
            or len(set(admin_user_ids)) != len(admin_user_ids)
            or any(type(uid) is not int or uid <= 0 for uid in admin_user_ids)
        ):
            raise TenantCreationFailedError()
        transaction = TransactionIdentity.capture(session)
        with bypass_tenant_filter():
            session.add(tenant)
            await session.flush()
            transaction.assert_current(session)
            department = Department(
                dept_id=department_id,
                name=tenant.tenant_name,
                tenant_id=tenant.id,
                parent_id=None,
                path="",
                source="local",
                external_id=department_id,
                status="active",
            )
            session.add(department)
            await session.flush()
            transaction.assert_current(session)
            department.path = f"/{department.id}/"
            tenant.root_dept_id = department.id
            await session.flush()
            transaction.assert_current(session)
            values = [
                {"user_id": uid, "tenant_id": tenant.id, "is_default": 0, "status": "active", "is_active": None}
                for uid in admin_user_ids
            ]
            for offset in range(0, len(values), 200):
                await session.execute(insert(UserTenant.__table__), values[offset : offset + 200])
                transaction.assert_current(session)
        return tenant

    async def acreate_mounted(self, session, *, tenant, department_id, department_tenant_id):
        from sqlalchemy import update

        if (
            not isinstance(session, AsyncSession)
            or type(tenant) is not Tenant
            or tenant.id is not None
            or not session.in_transaction()
            or session.new
            or session.dirty
            or session.deleted
            or type(department_id) is not int
            or department_id <= 0
            or type(department_tenant_id) is not int
            or department_tenant_id <= 0
        ):
            raise TenantCreationFailedError()
        transaction = TransactionIdentity.capture(session)
        session.add(tenant)
        await session.flush()
        transaction.assert_current(session)
        result = await session.execute(
            update(Department.__table__)
            .where(
                Department.id == department_id,
                Department.tenant_id == department_tenant_id,
                Department.is_tenant_root == 0,
                Department.mounted_tenant_id.is_(None),
            )
            .values(is_tenant_root=1, mounted_tenant_id=tenant.id)
        )
        transaction.assert_current(session)
        if result.rowcount != 1:
            raise TenantCreationFailedError()
        return tenant
