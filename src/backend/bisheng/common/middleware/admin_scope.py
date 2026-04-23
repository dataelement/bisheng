"""F019-admin-tenant-scope HTTP middleware.

Consumes the Redis ``admin_scope:{user_id}`` key on management-API calls
and injects the effective scope into the request's ContextVars so
downstream tenant-filtering logic (via ``get_current_tenant_id``) can
read it without knowing about F019.

**Where in the stack**: this middleware is registered in ``main.py``
*before* ``CustomMiddleware`` in source order, which makes it the
*inner* middleware at runtime — its ``dispatch`` runs *after* the
CustomMiddleware has decoded the JWT and populated the
``visible_tenant_ids`` ContextVar. That ordering matters because:

  1. Only global super admins may have an active scope (INV-T14). This
     middleware deliberately re-verifies that with ``_check_is_global_super``
     so a caller cannot flip a scope-looking Redis key for someone else
     and have it honoured here.
  2. Non-management paths (business APIs like ``/api/v1/chat``) must be
     untouched by scope — we set ``_is_management_api`` to False and
     return immediately, which is the hot path for most requests.

**Sliding TTL**: every management API hit refreshes the scope's Redis TTL
to ``settings.multi_tenant.admin_scope_ttl_seconds`` (default 14400s). A
super admin who is actively managing a Child cannot be kicked out by
inactivity; a super admin who steps away for 4h loses the scope.
"""

from __future__ import annotations

from typing import Iterable

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.context.tenant import (
    set_admin_scope_tenant_id,
    set_is_management_api,
)
from bisheng.utils.http_middleware import (
    _check_is_global_super,
    _decode_jwt_subject,
    _extract_http_access_token,
)


# Path prefixes considered "management APIs" for the purpose of admin-scope.
# The list is deliberately conservative: admin-scope is a read-time filter,
# and wrapping the whole API surface with it would change business flows
# (chat, workflow execute, knowledge ingest) — not wanted. Adding a new
# prefix is a small, auditable change; keep it narrow.
MANAGEMENT_API_PREFIXES: tuple[str, ...] = (
    '/api/v1/llm',
    '/api/v1/roles',
    '/api/v1/audit_log',
    '/api/v1/admin',
)


def _is_management_api_path(path: str, prefixes: Iterable[str] = MANAGEMENT_API_PREFIXES) -> bool:
    return any(path.startswith(p) for p in prefixes)


def _redis_key(user_id: int) -> str:
    return f'admin_scope:{user_id}'


class AdminScopeMiddleware(BaseHTTPMiddleware):
    """Inject F019 admin-scope into ContextVars on management-API hits."""

    async def dispatch(self, request: Request, call_next):
        is_mgmt = _is_management_api_path(request.url.path)
        set_is_management_api(is_mgmt)

        if not is_mgmt:
            # Business APIs are unaffected by scope (AC-07). Fast path: no
            # JWT decode, no Redis read, no FGA check.
            return await call_next(request)

        token = _extract_http_access_token(request)
        if not token:
            return await call_next(request)

        subject = _decode_jwt_subject(token)
        if not subject:
            return await call_next(request)
        user_id = subject.get('user_id')
        if not user_id:
            return await call_next(request)

        try:
            is_super = await _check_is_global_super(int(user_id))
        except Exception as exc:  # noqa: BLE001 — middleware must fail-open
            logger.debug('AdminScopeMiddleware: super check failed: %s', exc)
            return await call_next(request)

        if not is_super:
            # Redis key may exist (left behind by a prior super admin session
            # whose role was revoked before the Celery sweep caught up); do
            # NOT read it — that would let a non-super be proxied into a
            # scope view. Fail-closed. Eventual consistency via AC-12 hook.
            return await call_next(request)

        try:
            redis = await get_redis_client()
            key = _redis_key(int(user_id))
            raw = await redis.aget(key)
        except Exception as exc:  # noqa: BLE001 — fail-open on Redis outage
            logger.debug('AdminScopeMiddleware: Redis read failed: %s', exc)
            return await call_next(request)

        if raw is None:
            return await call_next(request)

        try:
            set_admin_scope_tenant_id(int(raw))
        except (TypeError, ValueError):
            # Corrupt value (non-numeric) — skip injection and move on.
            return await call_next(request)

        # Sliding refresh. Do NOT block the request on a TTL update failure.
        try:
            await redis.aexpire_key(
                key, settings.multi_tenant.admin_scope_ttl_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug('AdminScopeMiddleware: TTL refresh failed: %s', exc)

        return await call_next(request)
