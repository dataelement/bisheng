"""TenantAdminService — Child Tenant admin lifecycle (F013 T07).

Owner: F013-tenant-fga-tree (v2.5.1).

Public surface:
- grant_tenant_admin(tenant_id, user_id) — write `tenant:{id}#admin → user:{uid}`
- revoke_tenant_admin(tenant_id, user_id) — delete the same tuple
- list_tenant_admins(tenant_id) — return user ids holding the admin tuple

Root tenant guard (INV-T3, AC-13): all mutating methods refuse the Root
tenant. Root admin authority is granted via `system:global#super_admin`,
not via tenant#admin tuples. The list endpoint returns an empty list for
Root by design (no tuples exist; calling FGA would simply return nothing).
"""

from __future__ import annotations

import logging
from typing import List

from bisheng.common.errcode.tenant import TenantNotFoundError
from bisheng.common.errcode.tenant_fga import (
    OpenFGAConnectionError,
    RootTenantAdminNotAllowedError,
)
from bisheng.core.openfga.manager import aget_fga_client
from bisheng.database.models.tenant import ROOT_TENANT_ID, TenantDao

logger = logging.getLogger(__name__)


class TenantAdminService:
    """Stateless service for Child Tenant admin grants."""

    @classmethod
    async def grant_tenant_admin(cls, tenant_id: int, user_id: int) -> None:
        """Add user as Child Admin of the given tenant.

        Raises RootTenantAdminNotAllowedError (19204) for the Root tenant.
        Raises OpenFGAConnectionError (19201) when the FGA client is missing.
        """
        await cls._guard_not_root(tenant_id)
        fga = await aget_fga_client()
        if fga is None:
            raise OpenFGAConnectionError()
        await fga.write_tuples(writes=[{
            'user': f'user:{user_id}',
            'relation': 'admin',
            'object': f'tenant:{tenant_id}',
        }])
        logger.info('Granted Child Admin: user=%s tenant=%s', user_id, tenant_id)

    @classmethod
    async def revoke_tenant_admin(cls, tenant_id: int, user_id: int) -> None:
        """Remove user from Child Admin of the given tenant."""
        await cls._guard_not_root(tenant_id)
        fga = await aget_fga_client()
        if fga is None:
            raise OpenFGAConnectionError()
        await fga.write_tuples(deletes=[{
            'user': f'user:{user_id}',
            'relation': 'admin',
            'object': f'tenant:{tenant_id}',
        }])
        logger.info('Revoked Child Admin: user=%s tenant=%s', user_id, tenant_id)

    @classmethod
    async def list_tenant_admins(cls, tenant_id: int) -> List[int]:
        """Return user ids holding direct admin tuple on the tenant.

        Root tenant always returns [] (no tenant#admin tuples by design).
        Returns [] when OpenFGA is unavailable (fail-closed read).
        """
        if tenant_id == ROOT_TENANT_ID:
            return []
        fga = await aget_fga_client()
        if fga is None:
            return []
        tuples = await fga.read_tuples(
            relation='admin',
            object=f'tenant:{tenant_id}',
        )
        return list(cls._extract_user_ids(tuples))

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

    @staticmethod
    def _extract_user_ids(tuples: List[dict]):
        """Yield integer user ids from raw FGA tuples; skip non-numeric entries."""
        for t in tuples:
            user = t.get('user', '')
            if not user.startswith('user:'):
                continue
            raw = user.split(':', 1)[1]
            try:
                yield int(raw)
            except ValueError:
                continue
