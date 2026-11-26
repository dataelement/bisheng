"""Tenant creation owns its normal transaction, independent of reference hints."""

from bisheng.core.database import get_async_db_session
from bisheng.department.domain.services.department_service import _get_dept_id_prefix, generate_dept_id
from bisheng.tenant.domain.repositories.tenant_creation_repository import TenantCreationRepository


async def create_tenant_with_coverage(*, tenant, admin_user_ids):
    # Keep the existing composition entry name for callers; no coverage gate.
    department_id = generate_dept_id(_get_dept_id_prefix())
    async with get_async_db_session() as session, session.begin():
        tenant = await TenantCreationRepository().acreate(
            session, tenant=tenant, department_id=department_id, admin_user_ids=admin_user_ids
        )
    return tenant


async def create_mounted_tenant_with_coverage(*, tenant, department_id, department_tenant_id):
    async with get_async_db_session() as session, session.begin():
        tenant = await TenantCreationRepository().acreate_mounted(
            session, tenant=tenant, department_id=department_id, department_tenant_id=department_tenant_id
        )
    return tenant
