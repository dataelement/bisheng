"""F011 TenantMountService — Child Tenant lifecycle + resource migration.

Implements spec AC-02, AC-03, AC-04a/b/c/d, AC-07:

  - ``mount_child``: global-super marks a department as a Child Tenant
    mount point. Enforces INV-T1 (2-layer lock), records audit_log.
  - ``unmount_child``: removes a Child mount with policy A (migrate
    resources to Root), B (archive in-place), or C (manual — MVP falls
    back to policy B + warning; UI flow deferred).
  - ``migrate_resources_from_root``: AC-04d Root→Child resource sinking
    (INV-T10 — the one path that does NOT go through F018 transfer-owner).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Literal, Optional, Set

from bisheng.common.errcode.tenant_tree import (
    TenantTreeMigrateConflictError,
    TenantTreeMigratePermissionError,
    TenantTreeMigrateSourceError,
    TenantTreeMountConflictError,
    TenantTreeNestingForbiddenError,
    TenantTreeRootDeptMountError,
)
from bisheng.database.models.audit_log import AuditLogDao
from bisheng.database.models.department import DepartmentDao
from bisheng.database.models.tenant import ROOT_TENANT_ID, Tenant, TenantDao
from bisheng.tenant.domain.constants import TenantAuditAction

logger = logging.getLogger(__name__)

# Root-owned resources that may be sunk into a Child via AC-04d. The
# resource_type string doubles as the table name — adding a type here
# requires the table to share the ``id`` / ``tenant_id`` shape.
_MIGRATABLE_RESOURCE_TABLES: Set[str] = {
    'knowledge', 'flow', 'assistant', 'channel', 't_gpts_tools',
}

# Business tables migrated out of the Child on policy-A unmount. Subset of
# F001 ``TENANT_TABLES`` — every entry must carry an ``id`` / ``tenant_id``
# column and have a production ORM owned by this codebase today.
_UNMOUNT_MIGRATE_TABLES: List[str] = [
    'flow', 'flowversion',
    'assistant', 'assistantlink',
    'knowledge', 'knowledgefile', 'qaknowledge',
    'channel', 'channel_info_source', 'channel_article_read',
    't_gpts_tools', 't_gpts_tools_type',
    'chatmessage', 'message_session',
    'tag', 'taglink',
    'evaluation', 'dataset',
    'marktask', 'markrecord', 'markappuser',
    'invitecode',
    'linsight_sop', 'linsight_sop_record',
    'linsight_session_version', 'linsight_execute_task',
]


def _require_super(operator) -> None:
    """Gate: raise 22010 if the operator is not a global super admin."""
    check = getattr(operator, 'is_global_super', None)
    if check is None or not check():
        raise TenantTreeMigratePermissionError()


class TenantMountService:
    """Stateless service implementing the Child Tenant lifecycle."""

    # -----------------------------------------------------------------------
    # mount_child
    # -----------------------------------------------------------------------

    @classmethod
    async def mount_child(
        cls,
        dept_id: int,
        tenant_code: str,
        tenant_name: str,
        operator,
    ) -> Tenant:
        """Mark ``dept_id`` as a Child Tenant root (AC-02)."""
        _require_super(operator)
        dept = await DepartmentDao.aget_by_id(dept_id)
        if dept is None:
            raise TenantTreeMountConflictError()
        if dept.parent_id is None:
            # Root department — never a mount point (AC-03).
            raise TenantTreeRootDeptMountError()
        if getattr(dept, 'is_tenant_root', 0) == 1:
            raise TenantTreeMountConflictError()
        ancestor = await DepartmentDao.aget_ancestors_with_mount(dept_id)
        if ancestor is not None:
            # Any ancestor already a mount point → INV-T1 2-layer lock.
            raise TenantTreeNestingForbiddenError()

        new_tenant = Tenant(
            tenant_code=tenant_code,
            tenant_name=tenant_name,
            parent_tenant_id=ROOT_TENANT_ID,
            status='active',
        )
        new_tenant = await TenantDao.acreate_tenant(new_tenant)
        await DepartmentDao.aset_mount(dept_id, new_tenant.id)
        await _safe_audit(
            tenant_id=new_tenant.id,
            operator_id=getattr(operator, 'user_id', 0),
            operator_tenant_id=ROOT_TENANT_ID,
            action=TenantAuditAction.MOUNT.value,
            target_type='tenant',
            target_id=str(new_tenant.id),
            metadata={
                'dept_id': dept_id,
                'dept_path': getattr(dept, 'path', None),
                'tenant_code': tenant_code,
            },
        )
        return new_tenant

    # -----------------------------------------------------------------------
    # unmount_child
    # -----------------------------------------------------------------------

    @classmethod
    async def unmount_child(
        cls,
        dept_id: int,
        policy: Literal['migrate', 'archive', 'manual'],
        operator,
    ) -> Dict[str, Any]:
        """Reverse a mount. ``policy`` drives resource handling (AC-04a/b/c)."""
        _require_super(operator)
        dept = await DepartmentDao.aget_by_id(dept_id)
        if dept is None or not getattr(dept, 'mounted_tenant_id', None):
            raise TenantTreeMountConflictError()
        child_tenant_id: int = dept.mounted_tenant_id

        migrated_counts: Optional[Dict[str, int]] = None
        if policy == 'migrate':
            migrated_counts = await cls._migrate_child_resources_to_root(
                child_tenant_id,
            )
            # Archive the (now empty) Child so the record survives for audit.
            await TenantDao.aupdate_tenant(child_tenant_id, status='archived')
            await DepartmentDao.aunset_mount(dept_id)
        elif policy == 'archive':
            await TenantDao.aupdate_tenant(child_tenant_id, status='archived')
            await DepartmentDao.aunset_mount(dept_id)
        elif policy == 'manual':
            # MVP: spec AC-04c defers the UI flow. Fall back to archive
            # + warn; callers intending true manual handling should go
            # through F018 transfer-owner per resource first.
            logger.warning(
                'Manual unmount policy for dept %s: MVP falls back to archive',
                dept_id,
            )
            await TenantDao.aupdate_tenant(child_tenant_id, status='archived')
            await DepartmentDao.aunset_mount(dept_id)
        else:
            raise TenantTreeMountConflictError()

        meta: Dict[str, Any] = {'policy': policy, 'dept_id': dept_id}
        if migrated_counts is not None:
            meta['migrated_counts'] = migrated_counts
        await _safe_audit(
            tenant_id=child_tenant_id,
            operator_id=getattr(operator, 'user_id', 0),
            operator_tenant_id=ROOT_TENANT_ID,
            action=TenantAuditAction.UNMOUNT.value,
            target_type='tenant',
            target_id=str(child_tenant_id),
            metadata=meta,
        )
        result: Dict[str, Any] = {'policy': policy, 'tenant_id': child_tenant_id}
        if migrated_counts is not None:
            result['migrated_counts'] = migrated_counts
        return result

    @classmethod
    async def _migrate_child_resources_to_root(
        cls, child_tenant_id: int,
    ) -> Dict[str, int]:
        """Move every tenant-aware row from Child → Root via TenantDao.

        Thin delegate over ``TenantDao.abulk_update_tenant_id`` so the
        service layer does not own raw SQL — kept only as a semantic
        wrapper (fixed table whitelist, fixed from=child / to=Root).
        """
        return await TenantDao.abulk_update_tenant_id(
            tables=_UNMOUNT_MIGRATE_TABLES,
            from_tenant_id=child_tenant_id,
            to_tenant_id=ROOT_TENANT_ID,
        )

    # -----------------------------------------------------------------------
    # migrate_resources_from_root (AC-04d)
    # -----------------------------------------------------------------------

    @classmethod
    async def migrate_resources_from_root(
        cls,
        child_id: int,
        resource_type: str,
        resource_ids: List[int],
        operator,
        new_owner_user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Sink Root-owned resources into a Child Tenant.

        Enforces:
          - super-admin only (22010).
          - each resource.tenant_id == 1 (22011 for the rest, not blocking).
          - resource_type must be in the ``_MIGRATABLE_RESOURCE_TABLES``
            allowlist (unknown types → TenantTreeMountConflictError).

        Returns ``{migrated: N, failed: [{resource_id, reason}, ...]}``.
        """
        _require_super(operator)
        if resource_type not in _MIGRATABLE_RESOURCE_TABLES:
            # 22006 distinguishes "unknown resource_type" from 22002 "mount conflict".
            raise TenantTreeMigrateConflictError()
        if not resource_ids:
            return {'migrated': 0, 'failed': []}
        table = resource_type

        tenant_ids_by_resource = await cls._fetch_resource_tenant_ids(
            table, resource_ids,
        )

        passable: List[int] = []
        failed: List[Dict[str, Any]] = []
        for rid in resource_ids:
            current = tenant_ids_by_resource.get(rid)
            if current == ROOT_TENANT_ID:
                passable.append(rid)
            else:
                failed.append({
                    'resource_id': rid,
                    'reason': (
                        f'{TenantTreeMigrateSourceError.Code}: '
                        f'expected tenant_id=1 (Root), got {current!r}'
                    ),
                })

        if passable:
            await cls._update_resource_tenant_id(table, passable, child_id)

        await _safe_audit(
            tenant_id=child_id,
            operator_id=getattr(operator, 'user_id', 0),
            operator_tenant_id=ROOT_TENANT_ID,
            action=TenantAuditAction.RESOURCE_MIGRATE.value,
            target_type='resource_batch',
            target_id=resource_type,
            metadata={
                'from_tenant_id': ROOT_TENANT_ID,
                'to_tenant_id': child_id,
                'resource_type': resource_type,
                'count': len(passable),
                'resource_ids': passable,
                'failed_count': len(failed),
                'new_owner_user_id': new_owner_user_id,
            },
        )
        return {'migrated': len(passable), 'failed': failed}

    @classmethod
    async def _fetch_resource_tenant_ids(
        cls, table: str, resource_ids: List[int],
    ) -> Dict[int, int]:
        """Delegate to ``TenantDao.afetch_resource_tenant_ids``."""
        return await TenantDao.afetch_resource_tenant_ids(table, resource_ids)

    @classmethod
    async def _update_resource_tenant_id(
        cls, table: str, resource_ids: List[int], new_tenant_id: int,
    ) -> None:
        """Delegate to ``TenantDao.aupdate_resource_tenant_ids``."""
        await TenantDao.aupdate_resource_tenant_ids(
            table, resource_ids, new_tenant_id,
        )


# ---------------------------------------------------------------------------
# Best-effort audit helper: mount/unmount/migrate must write audit_log per
# AC-07, but the main transaction should not be rolled back if audit insert
# itself fails. spec §5.4 calls this "fail-open with logger.error".
# ---------------------------------------------------------------------------

async def _safe_audit(**kwargs: Any) -> None:
    try:
        await AuditLogDao.ainsert_v2(**kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            'audit_log insert failed for action=%s: %s',
            kwargs.get('action'), exc,
        )
