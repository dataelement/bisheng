"""Tenant-owned Child Tenant admin lifecycle (F013 T07).

Owner: F013-tenant-fga-tree (v2.5.1).

Public surface:
- grant_tenant_admin(tenant_id, user_id) — grant Child Admin
- revoke_tenant_admin(tenant_id, user_id) — revoke Child Admin
- list_tenant_admins(tenant_id) — list directly assigned Child Admins

Root tenant guard (INV-T3, AC-13): all mutating methods refuse the Root
tenant. Root authority is managed by the global super-admin permission. The
list endpoint returns an empty list for Root by design.
"""

from __future__ import annotations

from loguru import logger

from bisheng.common.errcode.tenant import TenantNotFoundError
from bisheng.common.errcode.tenant_fga import (
    PermissionBackendUnavailableError,
    RootTenantAdminNotAllowedError,
)
from bisheng.database.models.tenant import ROOT_TENANT_ID, TenantDao
from bisheng.permission.application import (
    PermissionObject,
    PermissionRelation,
    PermissionSubject,
    get_permission_relation_api,
)


class TenantAdminService:
    """Stateless service for Child Tenant admin grants."""

    @classmethod
    async def grant_tenant_admin(cls, tenant_id: int, user_id: int) -> None:
        """Add user as Child Admin of the given tenant.

        Raises RootTenantAdminNotAllowedError (19204) for the Root tenant.
        Raises PermissionBackendUnavailableError (19201) when permissions are unavailable.
        Raises ServiceAccountOperationForbiddenError (26022) for a service
        account: F049 AC-22 — a credential must never have an administrator
        identity behind it.
        """
        # Root guard first: it must stay a pure short-circuit that touches
        # neither the database nor the permission backend.
        await cls._guard_not_root(tenant_id)

        from bisheng.user.domain.services.user import UserService

        await UserService.aassert_natural_persons([user_id])
        relation = PermissionRelation(
            subject=PermissionSubject("user", str(user_id)),
            relation="admin",
            resource=PermissionObject("tenant", str(tenant_id)),
        )
        try:
            permissions = await get_permission_relation_api()
            await permissions.grant((relation,))
        except Exception as exc:
            raise PermissionBackendUnavailableError() from exc
        logger.info(
            "Granted Child Admin: user={} tenant={}",
            user_id,
            tenant_id,
        )

    @classmethod
    async def revoke_tenant_admin(cls, tenant_id: int, user_id: int) -> None:
        """Remove user from Child Admin of the given tenant."""
        await cls._guard_not_root(tenant_id)
        relation = PermissionRelation(
            subject=PermissionSubject("user", str(user_id)),
            relation="admin",
            resource=PermissionObject("tenant", str(tenant_id)),
        )
        try:
            permissions = await get_permission_relation_api()
            await permissions.revoke((relation,))
        except Exception as exc:
            raise PermissionBackendUnavailableError() from exc
        logger.info(
            "Revoked Child Admin: user={} tenant={}",
            user_id,
            tenant_id,
        )

    @classmethod
    async def list_tenant_admins(cls, tenant_id: int) -> list[int]:
        """Return user IDs holding a direct admin relation on the tenant.

        Root tenant always returns []. Permission failures fail closed.
        """
        if tenant_id == ROOT_TENANT_ID:
            return []
        try:
            permissions = await get_permission_relation_api()
            user_ids = await permissions.list_subject_ids(
                resource=PermissionObject("tenant", str(tenant_id)),
                relation="admin",
                subject_type="user",
            )
        except Exception:
            return []
        return [int(user_id) for user_id in user_ids if user_id.isdigit()]

    # ── Internal helpers ────────────────────────────────────────

    @classmethod
    async def _guard_not_root(cls, tenant_id: int) -> None:
        """Reject Root-tenant admin grants. Error semantics split:

        - tenant_id == ROOT_TENANT_ID (fast path): 19204 RootTenantAdminNotAllowed
        - tenant not found in DB: 20000 TenantNotFound (avoids leaking Root-only
          language back to callers who mistyped an id)
        - tenant.parent_tenant_id IS NULL (defensive, catches future Root rename
          or multiple rows without parent): 19204 RootTenantAdminNotAllowed
        """
        if tenant_id == ROOT_TENANT_ID:
            raise RootTenantAdminNotAllowedError()
        tenant = await TenantDao.aget_by_id(tenant_id)
        if tenant is None:
            raise TenantNotFoundError()
        if tenant.parent_tenant_id is None:
            raise RootTenantAdminNotAllowedError()
