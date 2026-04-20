"""TenantResolver — derive a user's leaf tenant from their primary department.

v2.5.1 F012: replaces v2.5.0's fallback ``tenant_id = DEFAULT_TENANT_ID`` login
behaviour. The resolver walks the user's primary department path, finds the
nearest ancestor that is a Tenant mount point (``is_tenant_root=1``), and
returns the Tenant it points to. If the mount-point Tenant is non-active
(``disabled`` / ``archived`` / ``orphaned``), the resolver walks further up
looking for the next active mount point. If no active mount point exists, the
user falls back to Root (``tenant_id = 1``).

Invariants:
  - No primary department → Root (audit later by UserTenantSyncService with
    ``reason='no_primary_department'``).
  - Mount-point → Tenant that's non-active → keep walking up; never fall
    through to Root silently while an active ancestor exists.
  - Self-referential path / cycle → raise ``TenantCycleDetectedError``.

All lookups happen inside ``bypass_tenant_filter()`` because we intentionally
query across tenants to determine which tenant the user belongs to.
"""

from typing import List, Optional

from loguru import logger

from bisheng.common.errcode.tenant_resolver import TenantCycleDetectedError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.department import (
    Department,
    DepartmentDao,
    UserDepartmentDao,
)
from bisheng.database.models.tenant import ROOT_TENANT_ID, Tenant, TenantDao


def _parent_dept_id_from_path(path: str, current_id: int) -> Optional[int]:
    """Return the parent department id of ``current_id`` within ``path``.

    ``path`` is the materialized path ``/1/5/12/``. This walks segments
    left-to-right and returns the segment immediately before the first
    occurrence of ``current_id``. Returns ``None`` if there is no parent
    (current is the root segment or path is empty).
    """
    if not path:
        return None
    segments: List[int] = []
    for part in path.split('/'):
        if part and part.isdigit():
            segments.append(int(part))
    try:
        idx = segments.index(current_id)
    except ValueError:
        # current_id not in path — treat current as leaf beyond path
        return segments[-1] if segments else None
    if idx == 0:
        return None
    return segments[idx - 1]


class TenantResolver:
    """Stateless service — all methods are classmethods, no instantiation."""

    @classmethod
    async def resolve_user_leaf_tenant(cls, user_id: int) -> Tenant:
        """Return the Tenant the user belongs to.

        Always returns a non-null Tenant; falls back to Root on any of the
        following: no primary department, no mount point on the path,
        all candidate mount points link to non-active tenants.
        """
        with bypass_tenant_filter():
            primary = await UserDepartmentDao.aget_user_primary_department(user_id)
            if primary is None:
                # F012 spec §5.1: no primary dept → Root. The caller
                # (UserTenantSyncService) writes the audit with
                # reason='no_primary_department'.
                return await cls._get_tenant_or_root(ROOT_TENANT_ID)

            return await cls._walk_from_dept(primary.department_id)

    @classmethod
    async def _walk_from_dept(cls, dept_id: int) -> Tenant:
        """Starting from ``dept_id``, find the nearest active mount-point
        Tenant; fall back to Root.
        """
        visited_dept_ids: set[int] = set()
        current_dept_id: Optional[int] = dept_id

        while current_dept_id is not None:
            if current_dept_id in visited_dept_ids:
                # Self-referential path — should never happen under F002
                # materialized path contract, but surface it loudly.
                logger.error(
                    'Tenant cycle detected in department path starting from %d',
                    dept_id,
                )
                raise TenantCycleDetectedError()
            visited_dept_ids.add(current_dept_id)

            mount_dept: Optional[Department] = (
                await DepartmentDao.aget_ancestors_with_mount(current_dept_id)
            )
            if mount_dept is None:
                break  # no more mount points up the tree

            tenant: Optional[Tenant] = None
            if mount_dept.mounted_tenant_id is not None:
                tenant = await TenantDao.aget_by_id(mount_dept.mounted_tenant_id)
            if tenant is not None and tenant.status == 'active':
                return tenant

            # Non-active (or missing) → skip this mount point and continue
            # up from its parent department. If the mount dept is self-
            # rooted (no parent in path), we're done.
            parent_id = _parent_dept_id_from_path(
                mount_dept.path or '', mount_dept.id
            )
            current_dept_id = parent_id

        return await cls._get_tenant_or_root(ROOT_TENANT_ID)

    @classmethod
    async def _get_tenant_or_root(cls, tenant_id: int) -> Tenant:
        """Fetch a Tenant; fall back to Root (id=1) when a non-Root id is missing.

        Root is guaranteed to exist by F011's migration. If Root itself is
        missing the DB is corrupt — raise ``TenantResolveFailedError`` so the
        operator sees the failure instead of a synthesized phantom row.
        """
        tenant = await TenantDao.aget_by_id(tenant_id)
        if tenant is not None:
            return tenant
        if tenant_id == ROOT_TENANT_ID:
            from bisheng.common.errcode.tenant_resolver import TenantResolveFailedError
            logger.error(
                'Root Tenant (id=%d) missing — F011 migration may not have run',
                ROOT_TENANT_ID,
            )
            raise TenantResolveFailedError()
        return await cls._get_tenant_or_root(ROOT_TENANT_ID)
