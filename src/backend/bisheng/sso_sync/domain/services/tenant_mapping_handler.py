"""Auto-mount Child Tenants directly from Gateway-pushed SSO payloads.

PRD §5.2.3 describes ``tenant_mapping`` as an *auxiliary* input used the
first time a department carrying business-unit significance appears in
bisheng. The handler is deliberately permissive:

- It **skips** already-mounted departments (``is_tenant_root=1``) — bisheng
  state wins over SSO declarations.
- It **skips** departments whose SSO record has not been pushed yet
  (a race between ``tenant_mapping`` and the upstream ``/departments/sync``
  batch). Logged as a warning; the next login with the same mapping will
  retry.
- It **raises 19302** when a parent in the path is already a mount point
  (INV-T1: only a 2-level tenant tree is permitted).
- It **bypasses** :class:`TenantMountService` ``_require_super`` check.
  Gateway is an out-of-band trusted system; authorisation is established
  by the HMAC signature, not by a JWT principal. The resulting audit row
  is stamped ``operator_id=0`` + ``metadata.via='sso_realtime'`` so the
  provenance is unambiguous.
"""

from typing import Iterable

from loguru import logger

from bisheng.common.errcode.sso_sync import SsoDeptMountConflictError
from bisheng.database.models.audit_log import AuditLogDao
from bisheng.database.models.department import DepartmentDao
from bisheng.database.models.tenant import (
    ROOT_TENANT_ID,
    Tenant,
    TenantDao,
)
from bisheng.sso_sync.domain.constants import SSO_SOURCE
from bisheng.sso_sync.domain.schemas.payloads import TenantMappingItem
from bisheng.tenant.domain.constants import TenantAuditAction


class TenantMappingHandler:

    SOURCE = SSO_SOURCE

    @classmethod
    async def process(
        cls,
        mappings: Iterable[TenantMappingItem],
        request_ip: str = '',
    ) -> None:
        for item in mappings or []:
            await cls._process_one(item, request_ip=request_ip)

    @classmethod
    async def _process_one(
        cls, item: TenantMappingItem, request_ip: str,
    ) -> None:
        dept = await DepartmentDao.aget_by_source_external_id(
            cls.SOURCE, item.dept_external_id,
        )
        if dept is None or dept.is_deleted == 1:
            logger.warning(
                'F014 tenant_mapping: dept %s not synced yet, skipping',
                item.dept_external_id,
            )
            return
        if int(dept.is_tenant_root or 0) == 1:
            # Idempotent: bisheng already considers this a mount point.
            # Even if SSO tries to rename/reassign, we keep bisheng state.
            return

        ancestor_mount = await DepartmentDao.aget_ancestors_with_mount(dept.id)
        if ancestor_mount is not None and ancestor_mount.id != dept.id:
            raise SsoDeptMountConflictError.http_exception(
                f'dept {dept.id} ({item.dept_external_id}) parent chain '
                f'already mounted to tenant {ancestor_mount.mounted_tenant_id}'
            )

        tenant = await TenantDao.acreate_tenant(Tenant(
            tenant_code=item.tenant_code,
            tenant_name=item.tenant_name,
            parent_tenant_id=ROOT_TENANT_ID,
            status='active',
        ))
        await DepartmentDao.aset_mount(dept.id, tenant.id)

        await AuditLogDao.ainsert_v2(
            tenant_id=tenant.id,
            operator_id=0,
            operator_tenant_id=ROOT_TENANT_ID,
            action=TenantAuditAction.MOUNT.value,
            target_type='tenant',
            target_id=str(tenant.id),
            metadata={
                'dept_id': dept.id,
                'dept_external_id': item.dept_external_id,
                'tenant_code': item.tenant_code,
                'via': 'sso_realtime',
            },
            ip_address=request_ip,
        )
