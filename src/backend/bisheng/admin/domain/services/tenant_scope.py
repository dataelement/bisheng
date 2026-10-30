"""A management view always names one active tenant, independently of identity."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger

from bisheng.admin.domain.repositories.tenant_scope_repository import TenantScopeRepository
from bisheng.common.errcode.admin_scope import (
    AdminScopeTenantNotFoundError,
    AdminScopeTenantRequiredError,
    AdminScopeUnavailableError,
)
from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.database.models.audit_log import AuditLogDao
from bisheng.database.models.tenant import ROOT_TENANT_ID
from bisheng.tenant.domain.constants import TenantAuditAction

REDIS_KEY_TEMPLATE = "admin_scope:{user_id}"


def _redis_key(user_id: int) -> str:
    return REDIS_KEY_TEMPLATE.format(user_id=user_id)


def _iso_expiry(ttl_seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=ttl_seconds)).isoformat()


def _selected_id(raw) -> int | None:
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("ascii")
        except UnicodeDecodeError:
            return None
    if isinstance(raw, str) and raw.isascii() and raw.isdigit():
        raw = int(raw)
    return raw if type(raw) is int and raw > 0 else None


class TenantScopeService:
    """Redis selection is a view preference, never a tenant or permission grant."""

    REDIS_KEY_TEMPLATE = REDIS_KEY_TEMPLATE

    @classmethod
    async def _own_tenant(cls, user_id: int) -> int:
        try:
            tenants = (
                await TenantScopeRepository.own_tenant_ids(user_id)
                if settings.multi_tenant.enabled
                else (ROOT_TENANT_ID,)
            )
            if len(tenants) == 1 and await TenantScopeRepository.status(tenants[0]) == "active":
                return tenants[0]
        except Exception as exc:
            logger.opt(exception=True).warning("Management identity membership lookup failed")
            raise AdminScopeUnavailableError() from exc
        raise AdminScopeUnavailableError()

    @classmethod
    async def get_scope(cls, user_id: int, *, is_super: bool | None = None, for_write: bool = False) -> dict:
        if is_super is None:
            from bisheng.utils.http_middleware import _check_is_global_super

            is_super = await _check_is_global_super(user_id)
        if is_super:
            try:
                redis = await get_redis_client()
                key = _redis_key(user_id)
                selected = _selected_id(await redis.aget(key))
                if selected is not None:
                    ttl = await redis.attl(key)
                    if ttl is not None and ttl > 0 and await TenantScopeRepository.status(selected) == "active":
                        return {"scope_tenant_id": selected, "expires_at": _iso_expiry(ttl), "source": "selected"}
            except Exception as exc:
                # A read can use independently verified membership; an uncertain write cannot.
                logger.opt(exception=True).warning("Management tenant selection unavailable")
                if for_write:
                    raise AdminScopeUnavailableError() from exc
        own_tenant = await cls._own_tenant(user_id)
        return {"scope_tenant_id": own_tenant, "expires_at": None, "source": "own"}

    @classmethod
    async def set_scope(cls, user_id: int, tenant_id: int, request_context: Mapping[str, Any] | None = None) -> dict:
        # Callers authenticate the global-super role before invoking this mutation.
        if type(tenant_id) is not int or tenant_id <= 0:
            raise AdminScopeTenantRequiredError()
        if await TenantScopeRepository.status(tenant_id) != "active":
            raise AdminScopeTenantNotFoundError()
        previous = await cls.get_scope(user_id, is_super=True, for_write=True)
        own_tenant = await cls._own_tenant(user_id)
        ttl = settings.multi_tenant.admin_scope_ttl_seconds
        redis = await get_redis_client()
        await redis.aset(_redis_key(user_id), str(tenant_id), expiration=ttl)
        ctx = dict(request_context or {})
        await AuditLogDao.ainsert_v2(
            tenant_id=tenant_id,
            operator_id=user_id,
            operator_tenant_id=own_tenant,
            action=TenantAuditAction.ADMIN_SCOPE_SWITCH.value,
            metadata={
                "from_scope": previous["scope_tenant_id"],
                "to_scope": tenant_id,
                "ip": ctx.get("ip"),
                "user_agent": ctx.get("ua"),
            },
            ip_address=ctx.get("ip"),
        )
        return {"scope_tenant_id": tenant_id, "expires_at": _iso_expiry(ttl), "source": "selected"}

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
