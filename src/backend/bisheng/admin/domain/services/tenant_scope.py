"""F019-admin-tenant-scope (v2.5.1) — TenantScopeService.

The admin tenant-scope is a Redis-backed, 4h-sliding, JWT-independent
mechanism that lets a global super admin temporarily narrow the set of
tenants visible to *management* APIs (``/llm``, ``/roles``, ``/audit_log``,
``/admin/*``). Normal business APIs are not affected.

**Why not JWT?** Spec §5.1.5: the deprecated ``POST /user/switch-tenant``
returned 410 Gone (INV-T4 — user leaf is derived from primary department,
not chosen). admin-scope is orthogonal: it does not change user membership,
only the *management view*.

**Lifecycle**:
  - ``set_scope(user_id, tenant_id, ctx)`` writes/deletes the Redis key and
    records an ``admin.scope_switch`` audit row.
  - ``get_scope(user_id)`` reads the key and its remaining TTL.
  - ``clear_on_logout`` / ``clear_on_token_version_bump`` /
    ``clear_on_role_revoke`` are hook methods consumed by AuthService,
    UserTenantSyncService and RoleService respectively.

See ``features/v2.5.1/019-admin-tenant-scope/spec.md`` §5.2.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

from bisheng.common.errcode.admin_scope import AdminScopeTenantNotFoundError
from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.database.models.audit_log import AuditLogDao
from bisheng.database.models.tenant import ROOT_TENANT_ID, TenantDao
from bisheng.tenant.domain.constants import TenantAuditAction


REDIS_KEY_TEMPLATE = 'admin_scope:{user_id}'


def _redis_key(user_id: int) -> str:
    return REDIS_KEY_TEMPLATE.format(user_id=user_id)


def _iso_expiry(ttl_seconds: int) -> str:
    """Return an ISO-8601 UTC timestamp for now + ttl (for client display)."""
    return (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()


class TenantScopeService:
    """Redis-backed admin-scope state + hook entry points (INV-T14)."""

    # Exposed so tests and callers can reference the same template.
    REDIS_KEY_TEMPLATE: str = REDIS_KEY_TEMPLATE

    @classmethod
    async def set_scope(
        cls,
        user_id: int,
        tenant_id: Optional[int],
        request_context: Optional[Mapping[str, Any]] = None,
    ) -> dict:
        """Set, clear (``tenant_id=None``), or replace a scope for ``user_id``.

        Writes an ``admin.scope_switch`` audit row carrying both the previous
        and new scope values so operators can reconstruct who viewed what.

        Raises ``AdminScopeTenantNotFoundError`` (19702) if ``tenant_id`` is
        not None and does not match any ``tenant.id`` (AC-15).
        """
        ctx = dict(request_context or {})
        key = _redis_key(user_id)
        redis = await get_redis_client()

        old_raw = await redis.aget(key)
        old_scope = int(old_raw) if old_raw else None

        if tenant_id is None:
            await redis.adelete(key)
            expires_at: Optional[str] = None
        else:
            if not await TenantDao.aexists(tenant_id):
                raise AdminScopeTenantNotFoundError()
            ttl = settings.multi_tenant.admin_scope_ttl_seconds
            await redis.aset(key, str(tenant_id), expiration=ttl)
            expires_at = _iso_expiry(ttl)

        # Audit. operator_tenant_id is ROOT_TENANT_ID because the caller is
        # always the global super admin (enforced at the endpoint layer) and
        # INV-T11 guarantees Root is the only always-present tenant.
        await AuditLogDao.ainsert_v2(
            tenant_id=tenant_id if tenant_id is not None else ROOT_TENANT_ID,
            operator_id=user_id,
            operator_tenant_id=ROOT_TENANT_ID,
            action=TenantAuditAction.ADMIN_SCOPE_SWITCH.value,
            metadata={
                'from_scope': old_scope,
                'to_scope': tenant_id,
                'ip': ctx.get('ip'),
                'user_agent': ctx.get('ua'),
            },
            ip_address=ctx.get('ip'),
        )
        return {'scope_tenant_id': tenant_id, 'expires_at': expires_at}

    @classmethod
    async def get_scope(cls, user_id: int) -> dict:
        """Return the current scope + accurate remaining TTL for ``user_id``.

        Missing key → both fields ``None``. Key exists without TTL (``-1``)
        or not found (``-2``) also returns ``None`` for ``expires_at``.
        """
        key = _redis_key(user_id)
        redis = await get_redis_client()
        raw = await redis.aget(key)
        if raw is None:
            return {'scope_tenant_id': None, 'expires_at': None}

        ttl = await redis.attl(key)
        if ttl is None or ttl < 0:
            expires_at: Optional[str] = None
        else:
            expires_at = _iso_expiry(ttl)
        return {'scope_tenant_id': int(raw), 'expires_at': expires_at}

    # ------------------------------------------------------------------
    # Hook entry points (idempotent DEL on the user's key).
    # ------------------------------------------------------------------

    @classmethod
    async def clear_on_logout(cls, user_id: int) -> None:
        """Called from ``AuthService.logout`` (AC-10)."""
        await cls._clear(user_id)

    @classmethod
    async def clear_on_token_version_bump(cls, user_id: int) -> None:
        """Called from ``UserTenantSyncService.sync_user`` after
        ``token_version`` is incremented — the old JWT is invalid so any
        prior scope should die with it (AC-11)."""
        await cls._clear(user_id)

    @classmethod
    async def clear_on_role_revoke(cls, user_id: int) -> None:
        """Called when the super_admin role is revoked (AC-12).

        **Not currently wired** — no public API revokes the super_admin
        role as of v2.5.1 (``user_addrole`` and ``user_delete`` both
        refuse to operate on a super admin). The method is kept here as
        a public entry point for the future RoleService; AC-12 is
        covered in the meantime by the middleware's per-request
        ``_check_is_global_super`` re-verification (stale Redis keys
        cannot produce a scope for a revoked super admin).

        See ``features/v2.5.1/019-admin-tenant-scope/role-revoke-hook.md``
        for the full T10 research log. ``TODO(#F019-role-revoke)``.
        """
        await cls._clear(user_id)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @classmethod
    async def _clear(cls, user_id: int) -> None:
        redis = await get_redis_client()
        await redis.adelete(_redis_key(user_id))
