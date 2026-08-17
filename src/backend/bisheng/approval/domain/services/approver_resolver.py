from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def resolve_tenant_admin_user_ids(tenant_id: int) -> list[int]:
    """Real administrators of ``tenant_id``, with a Root-only fallback to platform super admins.

    This replaced a "pragmatic approximation" that resolved
    ``UserRoleDao.aget_roles_user([AdminRole])`` — every platform super admin,
    for **every** tenant, ignoring ``tenant_id`` entirely. In a multi-tenant
    deployment that funnelled every tenant's approvals onto the super admins
    while the people actually configured as tenant administrators received
    nothing (F055 AC-21).

    Two properties are load bearing:

    * **The fallback is conditional, not a union.** ``list_tenant_admins``
      returns ``[]`` for the Root tenant *by construction* (INV-T3: Root
      authority is the global super-admin permission, not a tenant admin
      grant), so a single-tenant deployment would otherwise resolve nobody and
      park its first publish in ``approver_empty``. Any other tenant that has
      no administrator resolves nobody on purpose — adding super admins there
      is exactly the defect this function exists to remove.
    * **It is not** ``ApprovalNotificationService._get_admin_recipient_ids``.
      That one is an unconditional union of super admins and tenant admins and
      must stay that way: it picks *notification recipients* for approval
      exceptions, where one extra reader is harmless. Approver resolution is
      the opposite — one extra resolved user is one more person who can decide.
      Merging the two in either direction breaks the other's contract.

    ``list_tenant_admins`` fails closed (returns ``[]`` when the permission
    backend is unreachable). That is deliberate: an empty approver set surfaces
    as an ``approver_empty`` exception an administrator can see and act on,
    which is strictly better than silently widening who may approve.
    """
    from bisheng.database.models.tenant import ROOT_TENANT_ID
    from bisheng.tenant.domain.services.tenant_admin_service import TenantAdminService

    try:
        user_ids = list(await TenantAdminService.list_tenant_admins(int(tenant_id)))
    except Exception:
        logger.exception("approver_resolver: failed to list tenant admins for tenant_id=%s", tenant_id)
        user_ids = []
    if user_ids or int(tenant_id) != ROOT_TENANT_ID:
        return [int(one) for one in user_ids]
    return await _platform_super_admin_user_ids()


async def _platform_super_admin_user_ids() -> list[int]:
    """Users holding ``AdminRole`` — the Root tenant's only possible approver source."""
    try:
        from bisheng.database.constants import AdminRole
        from bisheng.user.domain.models.user_role import UserRoleDao

        rows = await UserRoleDao.aget_roles_user([AdminRole])
        return [int(row.user_id) for row in rows if row.user_id]
    except Exception:
        logger.exception("approver_resolver: failed to resolve platform super admins")
        return []


async def resolve_approvers_from_sources(sources: list[dict], req: Any) -> list[int]:
    """Resolve the full approver user-id list from a node's ``sources`` config.

    Each entry in *sources* has at least a ``type`` key.  Supported types:

    ``direct_user``
        Explicit user IDs stored in ``user_ids`` (list[int]).

    ``department_admin``
        Admins of the applicant's department (from ``DepartmentAdminGrantDao``).
        Falls back to an empty list when ``applicant_department_id`` is unset.

    ``tenant_admin``
        Administrators of ``req.tenant_id`` (``TenantAdminService.list_tenant_admins``),
        falling back to platform super admins **only** for the Root tenant.
        See :func:`resolve_tenant_admin_user_ids`.

    ``knowledge_space_owner`` / ``knowledge_space_manager`` / ``space_admin``
        These are resolved by the specific scenario handler that knows the
        relevant space.  This utility returns an empty contribution for them —
        the handler is expected to override or augment as needed.

    ``channel_admin``
        Channel admins are scenario-specific; returns empty here.

    Unknown types are silently skipped with a warning.
    """
    seen: set[int] = set()
    result: list[int] = []

    def _add(uid: int) -> None:
        if uid not in seen:
            seen.add(uid)
            result.append(uid)

    for source in sources:
        source_type = source.get("type", "")

        if source_type == "direct_user":
            for uid in source.get("user_ids") or []:
                try:
                    _add(int(uid))
                except (TypeError, ValueError):
                    logger.warning("approver_resolver: invalid user_id %r in direct_user source", uid)

        elif source_type == "department_admin":
            dept_id = getattr(req, "applicant_department_id", None)
            if dept_id:
                try:
                    from bisheng.database.models.department_admin_grant import DepartmentAdminGrantDao

                    ids = await DepartmentAdminGrantDao.aget_user_ids_by_department(int(dept_id))
                    for uid in ids:
                        _add(uid)
                except Exception:
                    logger.exception("approver_resolver: failed to resolve department_admin for dept_id=%s", dept_id)

        elif source_type == "tenant_admin":
            # Administrators of *this* tenant (F055 AC-21), Root falling back to
            # platform super admins (AC-15). See resolve_tenant_admin_user_ids.
            tenant_id = getattr(req, "tenant_id", None)
            if tenant_id is None:
                logger.warning("approver_resolver: tenant_admin source on a request without tenant_id")
            else:
                for uid in await resolve_tenant_admin_user_ids(int(tenant_id)):
                    _add(uid)

        elif source_type in (
            "knowledge_space_owner",
            "knowledge_space_manager",
            "space_admin",
            "channel_admin",
            "channel_owner",
            "channel_manager",
        ):
            # These must be resolved by the scenario handler itself.
            pass

        else:
            logger.warning("approver_resolver: unknown source type %r, skipping", source_type)

    return result
