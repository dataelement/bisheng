# Define a custom middleware class
import http.cookies
from time import time
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from bisheng.core.context.tenant import DEFAULT_TENANT_ID, set_current_tenant_id
from bisheng.core.logger import trace_id_generator, trace_id_var
from bisheng.utils import get_request_ip

# Paths exempt from tenant context checks (login, env, health, docs, static)
TENANT_CHECK_EXEMPT_PATHS = (
    '/api/v1/user/login',
    '/api/v1/user/register',
    '/api/v1/user/sso',
    '/api/v1/user/ldap',
    '/api/v1/user/public_key',
    '/api/v1/user/switch-tenant',
    '/api/v1/user/tenants',
    '/api/v1/env',
    '/health',
    '/docs',
    '/openapi.json',
    '/redoc',
)

# v2.5.1 F012: Redis TTL for cached is_global_super FGA check.
_IS_SUPER_CACHE_TTL_SECONDS = 300


def _decode_jwt_subject(token: str) -> Optional[dict]:
    """Decode a JWT token and return the decoded subject dict, or None on failure."""
    try:
        from bisheng.user.domain.services.auth import AuthJwt
        return AuthJwt().decode_jwt_token(token)
    except Exception:
        return None


def _extract_tenant_id_from_token(token: str) -> int:
    """Decode JWT token and extract tenant_id. Returns DEFAULT_TENANT_ID on failure."""
    return _tenant_id_from_subject(_decode_jwt_subject(token))


def _tenant_id_from_subject(subject: Optional[dict]) -> int:
    if subject is None:
        return DEFAULT_TENANT_ID
    return subject.get('tenant_id', DEFAULT_TENANT_ID)


def _set_tenant_context(
    token: str = None,
    *,
    decoded_subject: Optional[dict] = None,
) -> int:
    """Set tenant context from JWT cookie token. Returns extracted tenant_id.

    Shared by HTTP and WS middleware. ``decoded_subject`` lets the HTTP
    middleware reuse a JWT decoded earlier in the same request, avoiding a
    second decode on the hot path.
    """
    try:
        if token:
            tid = (
                _tenant_id_from_subject(decoded_subject)
                if decoded_subject is not None
                else _extract_tenant_id_from_token(token)
            )
            set_current_tenant_id(tid)
            return tid
        else:
            from bisheng.common.services.config_service import settings
            if not settings.multi_tenant.enabled:
                set_current_tenant_id(DEFAULT_TENANT_ID)
            return DEFAULT_TENANT_ID
    except Exception:
        try:
            from bisheng.common.services.config_service import settings
            if not settings.multi_tenant.enabled:
                set_current_tenant_id(DEFAULT_TENANT_ID)
        except Exception:
            pass
        return DEFAULT_TENANT_ID


async def _validate_token_version(
    user_id: int, payload_token_version: int,
) -> bool:
    """Return True when the JWT ``token_version`` matches the DB value.

    Redis-cached with a 5min TTL (populated lazily by the DAO on miss). On
    any infra failure we **fail-open** — block only on a confirmed mismatch.
    """
    if not user_id:
        return True  # No user claim → let downstream auth handle.
    try:
        from bisheng.user.domain.models.user import UserDao
        current = await UserDao.aget_token_version(user_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug('token_version lookup failed for user %d: %s', user_id, exc)
        return True  # fail-open — don't lock users out on cache/DB hiccup
    return int(current) == int(payload_token_version)


async def _check_is_global_super(user_id: int) -> bool:
    """FGA check: ``user:{id} super_admin system:global`` with Redis caching.

    Used by the middleware to decide whether to inject an IN-list filter
    (non-super) or leave it open (super). Cache key:
    ``user:{id}:is_super`` (the key cleared alongside ``leaf_tenant`` in
    ``UserTenantSyncService._invalidate_redis_caches``).
    """
    if not user_id:
        return False
    cache_key = f'user:{user_id}:is_super'
    try:
        from bisheng.core.cache.redis_manager import get_redis_client
        redis = await get_redis_client()
        cached = await redis.aget(cache_key)
        if cached is not None:
            return bool(int(cached))
    except Exception:
        redis = None  # Fall through to FGA; no cache writes.

    is_super = False
    try:
        from bisheng.core.openfga.manager import aget_fga_client
        fga = await aget_fga_client()
        if fga is not None:
            is_super = await fga.check(
                user=f'user:{user_id}',
                relation='super_admin',
                object='system:global',
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug('FGA super-admin check failed for user %d: %s', user_id, exc)
        return False

    try:
        if redis is not None:
            await redis.aset(cache_key, int(is_super),
                             expiration=_IS_SUPER_CACHE_TTL_SECONDS)
    except Exception:
        pass
    return bool(is_super)


def _compute_visible_tenant_ids(
    tenant_id: int, is_global_super: bool,
) -> Optional[frozenset]:
    """Return the IN-list frozenset for ``visible_tenant_ids`` or None.

    - Global super without an active admin-scope: ``None`` (no filter).
    - Root user (tenant_id == 1): ``{1}``.
    - Child user (tenant_id != 1 and > 0): ``{tenant_id, 1}`` (own leaf
      plus Root for shared resource visibility).
    - tenant_id == 0 (pending selection): ``frozenset()`` — no resources
      visible, the tenant-status check above will 403 non-exempt paths.
    """
    if is_global_super:
        # F019 AdminScopeMiddleware may later override; default is wide open.
        return None
    if tenant_id == 1:
        return frozenset({1})
    if tenant_id and tenant_id > 0:
        return frozenset({tenant_id, 1})
    return frozenset()


async def _apply_token_version_and_visible(
    request: Request,
    token: str,
    *,
    decoded_subject: Optional[dict] = None,
) -> Optional[JSONResponse]:
    """Enforce token_version + set visible_tenant_ids from a decoded JWT.

    Returns a JSONResponse (401) when the token_version mismatches; None
    otherwise. ``decoded_subject`` lets the caller share a JWT decode across
    middleware steps so the same token isn't decoded twice.
    """
    subject = (
        decoded_subject if decoded_subject is not None
        else _decode_jwt_subject(token)
    )
    if subject is None:
        return None  # Undecodable tokens fall through to existing logic.

    user_id = subject.get('user_id')
    payload_tv = int(subject.get('token_version', 0) or 0)
    if user_id and not await _validate_token_version(user_id, payload_tv):
        return JSONResponse(
            status_code=401,
            content={
                'status_code': 19103,
                'status_message': 'token_version mismatch — please re-login',
                'data': None,
            },
        )

    from bisheng.core.context.tenant import set_visible_tenant_ids
    try:
        tenant_id = int(subject.get('tenant_id', 0) or 0)
        is_super = await _check_is_global_super(user_id) if user_id else False
        visible = _compute_visible_tenant_ids(tenant_id, is_super)
        set_visible_tenant_ids(visible)
    except Exception as exc:  # noqa: BLE001
        logger.debug('visible_tenant_ids computation failed: %s', exc)
    return None


class CustomMiddleware(BaseHTTPMiddleware):
    """HTTP request middleware — trace ID + tenant context injection."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        # Trace ID
        if request.headers.get('x-trace-id'):
            trace_id = request.headers.get('x-trace-id')
        else:
            trace_id = trace_id_generator()
        ip = get_request_ip(request)
        path = request.url
        trace_id_var.set(trace_id)

        # Tenant context injection from JWT cookie. Decode the JWT once and
        # share it with the F012 token_version + visible_tenant_ids step so
        # the same token isn't decoded twice on the hot path.
        token = request.cookies.get('access_token_cookie')
        decoded_subject = _decode_jwt_subject(token) if token else None
        tenant_id = _set_tenant_context(token, decoded_subject=decoded_subject)

        req_path = request.url.path
        is_exempt = req_path.startswith(TENANT_CHECK_EXEMPT_PATHS)
        if token and not is_exempt:
            denial = await _apply_token_version_and_visible(
                request, token, decoded_subject=decoded_subject,
            )
            if denial is not None:
                return denial

        # Tenant status checks (F010)
        if not is_exempt and token:
            # tenant_id=0 means pending tenant selection — block non-exempt paths
            if tenant_id == 0:
                return JSONResponse(
                    status_code=403,
                    content={'status_code': 20004, 'status_message': 'Missing tenant context', 'data': None},
                )
            # Check if tenant is disabled via Redis blacklist
            if tenant_id and tenant_id > 0:
                try:
                    from bisheng.core.cache.redis_manager import get_redis_client
                    redis_client = await get_redis_client()
                    from bisheng.tenant.domain.services.tenant_service import DISABLED_TENANT_KEY
                    if await redis_client.aget(DISABLED_TENANT_KEY.format(tenant_id)):
                        return JSONResponse(
                            status_code=403,
                            content={'status_code': 20001, 'status_message': 'Tenant is disabled', 'data': None},
                        )
                except Exception:
                    pass  # Redis unavailable — fail-open for middleware

        logger.info(f"| {ip} | {request.method} {path}")
        start_time = time()
        response = await call_next(request)
        process_time = round(time() - start_time, 4)
        response.headers["X-Process-Time"] = str(process_time)
        response.headers["X-Trace-ID"] = trace_id
        logger.info(f"| {ip} | {request.method} {path} | process_time={process_time}s")
        return response


class WebSocketLoggingMiddleware:
    """WebSocket middleware — trace ID + tenant context injection."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            trace_id = trace_id_generator()
            trace_id_var.set(trace_id)

            # Tenant context injection from JWT cookie
            token = self._get_cookie_from_scope(scope, 'access_token_cookie')
            _set_tenant_context(token)

        await self.app(scope, receive, send)

    @staticmethod
    def _get_cookie_from_scope(scope: dict, cookie_name: str):
        """Extract a cookie value from ASGI scope headers."""
        headers = dict(scope.get('headers', []))
        cookie_header = headers.get(b'cookie', b'').decode('utf-8', errors='ignore')
        if not cookie_header:
            return None
        cookies = http.cookies.SimpleCookie(cookie_header)
        morsel = cookies.get(cookie_name)
        return morsel.value if morsel else None
