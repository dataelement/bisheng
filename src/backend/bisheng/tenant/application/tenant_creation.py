"""Owned creation TX; original permissions and seeds remain after its close."""

from bisheng.core.database import get_async_db_session
from bisheng.department.domain.services.department_service import _get_dept_id_prefix, generate_dept_id
from bisheng.knowledge.application.unification_coverage import _certify_created_tenant, production_coverage_factory
from bisheng.knowledge.domain.repositories.unification_coverage_repository import UnificationCoverageRepository
from bisheng.tenant.domain.repositories.tenant_creation_repository import TenantCreationRepository


async def create_tenant_with_coverage(*, tenant, admin_user_ids):
    department_id = generate_dept_id(_get_dept_id_prefix())
    async with get_async_db_session() as session, session.begin():
        coverage = UnificationCoverageRepository()
        epoch = await coverage.aallocate_epoch(session)
        before = await production_coverage_factory(session).arequire_global_ready()
        tenant = await TenantCreationRepository().acreate(
            session, tenant=tenant, department_id=department_id, admin_user_ids=admin_user_ids
        )
        await _certify_created_tenant(
            session,
            tenant_id=tenant.id,
            prior_tenant_ids=before.verified_tenant_ids,
            prior_epoch=before.coverage_epoch,
            epoch=epoch,
        )
    return tenant


async def create_mounted_tenant_with_coverage(*, tenant, department_id, department_tenant_id):
    from loguru import logger

    from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError

    async with get_async_db_session() as session, session.begin():
        coverage = UnificationCoverageRepository()
        epoch = await coverage.aallocate_epoch(session)
        before = await production_coverage_factory(session).arequire_global_ready()
        tenant = await TenantCreationRepository().acreate_mounted(
            session, tenant=tenant, department_id=department_id, department_tenant_id=department_tenant_id
        )
        try:
            await _certify_created_tenant(
                session,
                tenant_id=tenant.id,
                prior_tenant_ids=before.verified_tenant_ids,
                prior_epoch=before.coverage_epoch,
                epoch=epoch,
            )
        except ReferenceCoverageNotReadyError as error:
            if error.kwargs.get("reason") not in {
                "production_coverage_created_tenant_business_not_empty",
                "production_coverage_created_tenant_deletion_evidence",
            }:
                raise
            # Preserve the original mount creation for an actually nonempty
            # identity, but never sign an empty certificate or report ready.
            logger.warning("Mounted tenant {} requires formal reference inventory", tenant.id)
    return tenant
